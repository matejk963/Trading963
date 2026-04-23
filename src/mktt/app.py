"""
MKTT — Matej Krajcovic Trading Tool
Flask web application
"""
from flask import Flask, render_template, request
from datetime import datetime
import pandas as pd
import time

from screener import (
    screen_stocks, get_available_sectors,
    EXCHANGES, EXCHANGE_NAMES
)
from stage_classifier import (
    run_stage_from_local_db, get_stage_distribution
)

app = Flask(__name__)


def fmt_number(val):
    """Format large numbers: 1.2B, 345M, 12.5K"""
    if val is None or val != val:
        return '—'
    val = float(val)
    if abs(val) >= 1e12:
        return f'{val/1e12:.1f}T'
    elif abs(val) >= 1e9:
        return f'{val/1e9:.1f}B'
    elif abs(val) >= 1e6:
        return f'{val/1e6:.1f}M'
    elif abs(val) >= 1e3:
        return f'{val/1e3:.0f}K'
    else:
        return f'{val:.0f}'


app.jinja_env.globals['fmt_number'] = fmt_number


@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}


@app.route('/')
@app.route('/screener')
def screener_page():
    preset = request.args.get('preset', 'all')
    min_turnover = int(float(request.args.get('min_turnover', '500000')))
    sector = request.args.get('sector', 'All')
    min_price = float(request.args.get('min_price', '0'))
    sort_by = request.args.get('sort_by', 'turnover' if preset == 'all' else 'rs')

    filters = {
        'preset': preset,
        'min_turnover': min_turnover,
        'sector': sector,
        'min_price': min_price,
        'sort_by': sort_by,
    }

    start = time.time()
    stage_dist = None
    market_regime = None
    universe_total = 0
    sectors = []

    if preset == 'all':
        # Plain screener — use Yahoo screen API
        exchange_codes = list(EXCHANGES['US'].keys())
        df = screen_stocks(
            exchange_codes,
            min_turnover=min_turnover,
            sector=sector,
            min_price=min_price,
            sort_by=sort_by,
        )
        sectors = get_available_sectors(exchange_codes)
        data = df.to_dict('records') if not df.empty else []

    else:
        # Stage preset — use local Parquet DB
        classified = run_stage_from_local_db(min_turnover=min_turnover, min_price=min_price or 5)

        if not classified.empty:
            universe_total = len(classified)
            stage_dist = get_stage_distribution(classified)

            # Market regime (based on classified stocks only, excluding stage 0)
            qualified = universe_total - stage_dist.get(0, {}).get('count', 0)
            s2_pct = (stage_dist.get(2, {}).get('count', 0) / qualified * 100) if qualified > 0 else 0
            s4_pct = (stage_dist.get(4, {}).get('count', 0) / qualified * 100) if qualified > 0 else 0
            if s2_pct >= 40 and s4_pct < 10:
                market_regime = 'Healthy Bull'
            elif s2_pct >= 25 and s4_pct < 20:
                market_regime = 'Late Bull'
            elif s2_pct < 20 and s4_pct >= 30:
                market_regime = 'Bear'
            elif s2_pct < 25 and s4_pct >= 20:
                market_regime = 'Bottoming'
            else:
                market_regime = 'Mixed'

            # Filter by selected stage
            if preset == 'stage2':
                classified = classified[classified['Stage'] == 2]
            elif preset == 'stage1':
                classified = classified[classified['Stage'] == 1]
            elif preset == 'stage3':
                classified = classified[classified['Stage'] == 3]
            elif preset == 'stage4':
                classified = classified[classified['Stage'] == 4]
            elif preset == 'trans12':
                classified = classified[classified['Transition'] == '1->2']

            # Apply sector filter
            if sector and sector != 'All' and 'Sector' in classified.columns:
                classified = classified[classified['Sector'] == sector]

            # Sort
            if not classified.empty:
                sort_map = {
                    'rs': ('RS_Rank', False),
                    'mansfield': ('Mansfield_RS', False),
                    'dist_high': ('Dist52wHigh%', True),
                    'turnover': ('ADV_Dollar', False),
                    'mcap': ('ADV_Dollar', False),
                    'change': ('Change%', False),
                }
                col, asc = sort_map.get(sort_by, ('RS_Rank', False))
                if col in classified.columns:
                    classified = classified.sort_values(col, ascending=asc, na_position='last')

            data = classified.to_dict('records') if not classified.empty else []
        else:
            data = []

    elapsed = time.time() - start
    fetch_time = f'Fetched in {elapsed:.1f}s'

    # Enrich all results with sector + PE from cached data
    sector_stats = []
    if data:
        results_df = pd.DataFrame(data)

        # Load sector map
        from data_manager import load_sector_map, build_sector_map, load_universe
        smap = load_sector_map()
        if smap is None:
            try:
                smap = build_sector_map()
            except Exception:
                smap = pd.DataFrame()

        # Enrich with sector
        if smap is not None and not smap.empty:
            sector_lookup = smap.set_index('symbol')['sector'].to_dict()
            results_df['Sector'] = results_df['Symbol'].map(sector_lookup)
            # Total stocks per sector (for normalization)
            sector_totals = smap['sector'].value_counts().to_dict()
        else:
            sector_totals = {}

        # Enrich with PE from universe metadata if missing
        if 'PE' not in results_df.columns or 'FwdPE' not in results_df.columns:
            uni = load_universe()
            if uni is not None:
                uni_lookup = uni.set_index('symbol')
                if 'trailingPE' in uni_lookup.columns and 'PE' not in results_df.columns:
                    results_df['PE'] = results_df['Symbol'].map(
                        uni_lookup['trailingPE'].to_dict())
                if 'forwardPE' in uni_lookup.columns and 'FwdPE' not in results_df.columns:
                    results_df['FwdPE'] = results_df['Symbol'].map(
                        uni_lookup['forwardPE'].to_dict())

        # Write enriched data back
        for i in range(len(data)):
            for col in ['Sector', 'PE', 'FwdPE']:
                if col in results_df.columns:
                    val = results_df.iloc[i].get(col)
                    data[i][col] = val if pd.notna(val) else None

        pe_col = 'PE' if 'PE' in results_df.columns else None
        fwdpe_col = 'FwdPE' if 'FwdPE' in results_df.columns else None

        if 'Sector' in results_df.columns:
            grouped = results_df.groupby('Sector')
            for sector_name, group in grouped:
                if not sector_name or pd.isna(sector_name):
                    continue

                total_in_sector = sector_totals.get(sector_name, len(group))
                stats = {
                    'sector': sector_name,
                    'count': len(group),
                    'total': total_in_sector,
                    'pct_of_sector': len(group) / total_in_sector * 100 if total_in_sector > 0 else 0,
                    'pct_of_results': len(group) / len(results_df) * 100,
                }
                if pe_col and pe_col in group.columns:
                    valid_pe = pd.to_numeric(group[pe_col], errors='coerce').dropna()
                    valid_pe = valid_pe[valid_pe > 0]
                    stats['median_pe'] = float(valid_pe.median()) if len(valid_pe) > 0 else None
                else:
                    stats['median_pe'] = None
                if fwdpe_col and fwdpe_col in group.columns:
                    valid_fpe = pd.to_numeric(group[fwdpe_col], errors='coerce').dropna()
                    valid_fpe = valid_fpe[valid_fpe > 0]
                    stats['median_fwd_pe'] = float(valid_fpe.median()) if len(valid_fpe) > 0 else None
                else:
                    stats['median_fwd_pe'] = None
                sector_stats.append(stats)

            sector_stats.sort(key=lambda x: x['pct_of_sector'], reverse=True)

    return render_template('screener.html',
                           data=data,
                           filters=filters,
                           sectors=sectors,
                           stage_dist=stage_dist,
                           market_regime=market_regime,
                           universe_total=universe_total,
                           sector_stats=sector_stats,
                           fetch_time=fetch_time)


@app.route('/chart/<symbol>')
def chart_page(symbol):
    """Render OHLC chart for a single symbol"""
    from data_manager import load_prices

    close = load_prices('close', tickers=[symbol])
    high = load_prices('high', tickers=[symbol])
    low = load_prices('low', tickers=[symbol])
    volume = load_prices('volume', tickers=[symbol])

    has_data = (close is not None and symbol in close.columns)

    chart_data = None
    if has_data:
        df = pd.DataFrame({
            'close': close[symbol],
            'high': high[symbol],
            'low': low[symbol],
            'volume': volume[symbol],
        }).dropna()

        # Synthesize open from previous close
        df['open'] = df['close'].shift(1)
        df = df.iloc[1:]  # Drop first row (no open)

        # Compute MAs
        df['ma_50'] = df['close'].rolling(50).mean()
        df['ma_150'] = df['close'].rolling(150).mean()
        df['ma_200'] = df['close'].rolling(200).mean()

        # Convert dates to plain YYYY-MM-DD strings
        dates = [str(d)[:10] for d in df.index]

        chart_data = {
            'dates': dates,
            'open': [round(v, 4) for v in df['open']],
            'close': [round(v, 4) for v in df['close']],
            'high': [round(v, 4) for v in df['high']],
            'low': [round(v, 4) for v in df['low']],
            'volume': [int(v) for v in df['volume']],
            'ma_50': [round(v, 4) if pd.notna(v) else None for v in df['ma_50']],
            'ma_150': [round(v, 4) if pd.notna(v) else None for v in df['ma_150']],
            'ma_200': [round(v, 4) if pd.notna(v) else None for v in df['ma_200']],
        }

    return render_template('chart.html', symbol=symbol, chart_data=chart_data, has_data=has_data)


if __name__ == '__main__':
    app.run(debug=True, port=5001, use_reloader=True, reloader_type='stat')
