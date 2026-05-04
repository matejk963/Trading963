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

# Register blueprints
from macro import macro_bp
app.register_blueprint(macro_bp)


# =========================================================================
# Refinitiv data enrichment
# =========================================================================
_refinitiv_cache = {'data': None, 'mtime': 0}

def load_refinitiv_snapshot():
    """Load Refinitiv snapshot as a symbol-keyed dict. Cached with mtime check."""
    import os, pickle
    from pathlib import Path
    pkl_path = Path(__file__).parent.parent.parent / 'data' / 'mktt' / 'refinitiv_fundamentals.pkl'
    if not pkl_path.exists():
        return {}
    mtime = os.path.getmtime(pkl_path)
    if _refinitiv_cache['data'] is not None and _refinitiv_cache['mtime'] == mtime:
        return _refinitiv_cache['data']
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    snap = data.get('snapshot')
    fy1 = data.get('fy1')
    fy2 = data.get('fy2')
    if snap is None:
        return {}
    lookup = {}
    for _, row in snap.iterrows():
        sym = row.get('Symbol')
        if pd.isna(sym):
            continue
        sym = str(sym)
        rec = {
            'sector': _safe_val(row.get('GICS Sector Name')),
            'industry': _safe_val(row.get('GICS Industry Name')),
            'eps_act': _safe_num(row.get('Earnings Per Share - Actual')),
            'eps_mean': _safe_num(row.get('Earnings Per Share - Mean')),
            'eps_smart': _safe_num(row.get('Earnings Per Share - SmartEstimate®')),
            'rev_act': _safe_num(row.get('Revenue - Actual')),
            'rev_mean': _safe_num(row.get('Revenue - Mean')),
            'op_margin': _safe_num(row.get('Operating Margin, Percent')),
            'net_margin': _safe_num(row.get('Net Profit Margin, (%)')),
            'ebitda': _safe_num(row.get('EBITDA')),
            'fcf': _safe_num(row.get('Free Cash Flow')),
            'total_debt': _safe_num(row.get('Total Debt')),
            'net_debt': _safe_num(row.get('Net Debt Incl. Pref.Stock & Min.Interest')),
            'cash': _safe_num(row.get('Cash and Short Term Investments')),
            'nd_ebitda': _safe_num(row.get('Net Debt To EBITDA (Daily Time Series Ratio)')),
            'current_ratio': _safe_num(row.get('Current Ratio')),
            'roic': _safe_num(row.get('Return on Capital, Total LT Capital, Percent')),
            'ev_ebitda': _safe_num(row.get('Enterprise Value To EBITDA (Daily Time Series Ratio)')),
            'target': _safe_num(row.get('Price Target - Mean')),
            'analysts': _safe_num(row.get('Number of Analysts')),
            'shares': _safe_num(row.get('Outstanding Shares')),
            'mktcap': None,  # compute from price * shares
        }
        # FY1/FY2 estimates
        if fy1 is not None:
            f1 = fy1[fy1['Symbol'] == sym]
            if len(f1) > 0:
                rec['fy1_eps'] = _safe_num(f1.iloc[0].get('Earnings Per Share - Mean'))
                rec['fy2_eps'] = None
        if fy2 is not None:
            f2 = fy2[fy2['Symbol'] == sym]
            if len(f2) > 0:
                rec['fy2_eps'] = _safe_num(f2.iloc[0].get('Earnings Per Share - Mean'))
        lookup[sym] = rec
    _refinitiv_cache['data'] = lookup
    _refinitiv_cache['mtime'] = mtime
    return lookup


def _safe_num(v):
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_val(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v) if str(v) != '<NA>' else None


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
        # Plain screener — use local Parquet DB + Refinitiv enrichment (no yfinance API call)
        from data_manager import load_prices, load_universe
        close = load_prices('close')
        uni = load_universe()
        rfv = load_refinitiv_snapshot()

        if close is not None and not close.empty:
            last_prices = close.iloc[-1]
            prev_prices = close.iloc[-2] if len(close) > 1 else last_prices

            # Compute RS rank (6-month return percentile)
            rs_ranks = {}
            if len(close) > 126:
                ret_6m = (close.iloc[-1] / close.iloc[-126] - 1)
                rs_pct = ret_6m.rank(pct=True) * 100
                rs_ranks = rs_pct.to_dict()

            rows = []
            for sym in close.columns:
                price = last_prices.get(sym)
                prev = prev_prices.get(sym)
                if pd.isna(price) or price <= 0:
                    continue
                if price < min_price:
                    continue

                # Get turnover from universe
                uni_row = uni[uni['symbol'] == sym].iloc[0] if uni is not None and sym in uni['symbol'].values else None
                turnover = float(uni_row['turnover']) if uni_row is not None and pd.notna(uni_row.get('turnover')) else 0
                if turnover < min_turnover:
                    continue

                r = rfv.get(sym, {})
                sec_name = r.get('sector', '')
                if sector and sector != 'All' and sec_name != sector:
                    continue

                change_pct = ((price / prev) - 1) * 100 if pd.notna(prev) and prev > 0 else 0

                rows.append({
                    'Symbol': sym,
                    'Price': round(float(price), 2),
                    'Change%': round(float(change_pct), 2),
                    'Sector': sec_name,
                    'Industry': r.get('industry', ''),
                    'ADV_Dollar': turnover,
                    'RS_Rank': round(rs_ranks.get(sym, 0), 0) if sym in rs_ranks else None,
                })

            df = pd.DataFrame(rows)
            if not df.empty:
                sort_col_map = {'turnover': 'ADV_Dollar', 'change': 'Change%'}
                sc = sort_col_map.get(sort_by, 'ADV_Dollar')
                if sc in df.columns:
                    df = df.sort_values(sc, ascending=False, na_position='last')
                # No limit — show all qualifying stocks
            data = df.to_dict('records') if not df.empty else []
        else:
            data = []

        # Get unique sectors for filter dropdown
        if rfv:
            sectors = sorted(set(r.get('sector', '') for r in rfv.values() if r.get('sector')))
        else:
            sectors = []

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

    # Enrich all results with Refinitiv fundamentals
    sector_stats = []
    if data:
        results_df = pd.DataFrame(data)
        rfv = load_refinitiv_snapshot()

        # Enrich with Refinitiv sector/industry (fallback to existing if no Refinitiv data)
        if rfv:
            results_df['Sector'] = results_df['Symbol'].map(lambda s: rfv.get(s, {}).get('sector'))
            results_df['Industry'] = results_df['Symbol'].map(lambda s: rfv.get(s, {}).get('industry'))
            # Refinitiv fundamental columns
            for col, key in [('EPS_Act', 'eps_act'), ('EPS_FY1', 'fy1_eps'), ('EPS_FY2', 'fy2_eps'),
                             ('OpMargin', 'op_margin'), ('NetMargin', 'net_margin'),
                             ('FCF', 'fcf'), ('ROIC', 'roic'), ('ND_EBITDA', 'nd_ebitda'),
                             ('EV_EBITDA', 'ev_ebitda'), ('Target', 'target'), ('Analysts', 'analysts')]:
                results_df[col] = results_df['Symbol'].map(lambda s, k=key: rfv.get(s, {}).get(k))
            # Compute PE and FwdPE from price and EPS
            if 'Price' in results_df.columns:
                results_df['PE'] = results_df.apply(
                    lambda r: r['Price'] / r['EPS_Act'] if pd.notna(r.get('Price')) and pd.notna(r.get('EPS_Act')) and r['EPS_Act'] > 0 else None, axis=1)
                results_df['FwdPE'] = results_df.apply(
                    lambda r: r['Price'] / r['EPS_FY1'] if pd.notna(r.get('Price')) and pd.notna(r.get('EPS_FY1')) and r['EPS_FY1'] > 0 else None, axis=1)
            # Sector totals from Refinitiv
            sector_totals = {}
            for rec in rfv.values():
                s = rec.get('sector')
                if s:
                    sector_totals[s] = sector_totals.get(s, 0) + 1
        else:
            # Fallback to yfinance-based enrichment
            from data_manager import load_sector_map, build_sector_map, load_universe
            smap = load_sector_map()
            if smap is None:
                try:
                    smap = build_sector_map()
                except Exception:
                    smap = pd.DataFrame()
            if smap is not None and not smap.empty:
                smap_indexed = smap.set_index('symbol')
                results_df['Sector'] = results_df['Symbol'].map(smap_indexed['sector'].to_dict())
                if 'industry' in smap_indexed.columns:
                    results_df['Industry'] = results_df['Symbol'].map(smap_indexed['industry'].to_dict())
                sector_totals = smap['sector'].value_counts().to_dict()
            else:
                sector_totals = {}
            if 'PE' not in results_df.columns or 'FwdPE' not in results_df.columns:
                uni = load_universe()
                if uni is not None:
                    uni_lookup = uni.set_index('symbol')
                    if 'trailingPE' in uni_lookup.columns and 'PE' not in results_df.columns:
                        results_df['PE'] = results_df['Symbol'].map(uni_lookup['trailingPE'].to_dict())
                    if 'forwardPE' in uni_lookup.columns and 'FwdPE' not in results_df.columns:
                        results_df['FwdPE'] = results_df['Symbol'].map(uni_lookup['forwardPE'].to_dict())

        # Write enriched data back
        enrich_cols = ['Sector', 'Industry', 'PE', 'FwdPE',
                       'EPS_Act', 'EPS_FY1', 'EPS_FY2', 'OpMargin', 'NetMargin',
                       'FCF', 'ROIC', 'ND_EBITDA', 'EV_EBITDA', 'Target', 'Analysts']
        for i in range(len(data)):
            for col in enrich_cols:
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
                def _median_of(col_name, positive_only=False):
                    if col_name not in group.columns:
                        return None
                    vals = pd.to_numeric(group[col_name], errors='coerce').dropna()
                    if positive_only:
                        vals = vals[vals > 0]
                    return float(vals.median()) if len(vals) > 0 else None

                stats['median_pe'] = _median_of('PE', positive_only=True)
                stats['median_fwd_pe'] = _median_of('FwdPE', positive_only=True)
                stats['median_eps'] = _median_of('EPS_Act')
                stats['median_fy1'] = _median_of('EPS_FY1')
                stats['median_fy2'] = _median_of('EPS_FY2')
                stats['median_op_margin'] = _median_of('OpMargin')
                stats['median_net_margin'] = _median_of('NetMargin')
                stats['median_roic'] = _median_of('ROIC')
                stats['median_fcf'] = _median_of('FCF')
                stats['median_nd_ebitda'] = _median_of('ND_EBITDA')
                stats['median_ev_ebitda'] = _median_of('EV_EBITDA', positive_only=True)
                stats['median_rs'] = _median_of('RS_Rank')
                stats['median_target'] = _median_of('Target')
                # Build stock entries
                def make_stock(row):
                    def _g(col):
                        v = row.get(col)
                        return v if pd.notna(v) else None
                    return {
                        'symbol': row.get('Symbol', ''),
                        'price': _g('Price'),
                        'change': _g('Change%'),
                        'pe': _g('PE'),
                        'fwd_pe': _g('FwdPE'),
                        'rs_rank': _g('RS_Rank'),
                        'mansfield': _g('Mansfield_RS'),
                        'industry': _g('Industry') or '',
                        'eps_act': _g('EPS_Act'),
                        'eps_fy1': _g('EPS_FY1'),
                        'eps_fy2': _g('EPS_FY2'),
                        'op_margin': _g('OpMargin'),
                        'net_margin': _g('NetMargin'),
                        'fcf': _g('FCF'),
                        'roic': _g('ROIC'),
                        'nd_ebitda': _g('ND_EBITDA'),
                        'ev_ebitda': _g('EV_EBITDA'),
                        'target': _g('Target'),
                        'analysts': _g('Analysts'),
                    }

                # All stocks flat list (sorted by RS)
                stock_list = [make_stock(row) for _, row in group.iterrows()]
                stock_list.sort(key=lambda x: x.get('rs_rank') or 0, reverse=True)
                stats['stocks'] = stock_list

                # Industry breakdown
                industries = []
                if 'Industry' in group.columns:
                    for ind_name, ind_group in group.groupby('Industry'):
                        if not ind_name or pd.isna(ind_name):
                            continue
                        ind_stocks = [make_stock(row) for _, row in ind_group.iterrows()]
                        ind_stocks.sort(key=lambda x: x.get('rs_rank') or 0, reverse=True)

                        def _ind_median(col_name, pos_only=False):
                            vals = pd.to_numeric(ind_group.get(col_name, pd.Series()), errors='coerce').dropna()
                            if pos_only: vals = vals[vals > 0]
                            return float(vals.median()) if len(vals) > 0 else None

                        industries.append({
                            'industry': ind_name,
                            'count': len(ind_group),
                            'median_pe': _ind_median('PE', pos_only=True),
                            'median_fwd_pe': _ind_median('FwdPE', pos_only=True),
                            'median_eps': _ind_median('EPS_Act'),
                            'median_fy1': _ind_median('EPS_FY1'),
                            'median_fy2': _ind_median('EPS_FY2'),
                            'median_op_margin': _ind_median('OpMargin'),
                            'median_net_margin': _ind_median('NetMargin'),
                            'median_roic': _ind_median('ROIC'),
                            'median_fcf': _ind_median('FCF'),
                            'median_nd_ebitda': _ind_median('ND_EBITDA'),
                            'median_ev_ebitda': _ind_median('EV_EBITDA', pos_only=True),
                            'median_rs': _ind_median('RS_Rank'),
                            'median_target': _ind_median('Target'),
                            'stocks': ind_stocks,
                        })
                    industries.sort(key=lambda x: x['count'], reverse=True)
                stats['industries'] = industries

                sector_stats.append(stats)

            sector_stats.sort(key=lambda x: x['pct_of_sector'], reverse=True)

    return render_template('screener.html',
                           active_section='screener',
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


@app.route('/api/chart/<symbol>')
def chart_api(symbol):
    """Return chart data as JSON for inline rendering"""
    from flask import jsonify
    from data_manager import load_prices

    close = load_prices('close', tickers=[symbol])
    high = load_prices('high', tickers=[symbol])
    low = load_prices('low', tickers=[symbol])
    volume = load_prices('volume', tickers=[symbol])

    if close is None or symbol not in close.columns:
        return jsonify({'error': 'No data'}), 404

    df = pd.DataFrame({
        'close': close[symbol], 'high': high[symbol],
        'low': low[symbol], 'volume': volume[symbol],
    }).dropna()

    df['open'] = df['close'].shift(1)
    df = df.iloc[1:]
    df['ma_50'] = df['close'].rolling(50).mean()
    df['ma_150'] = df['close'].rolling(150).mean()
    df['ma_200'] = df['close'].rolling(200).mean()

    return jsonify({
        'dates': [str(d)[:10] for d in df.index],
        'open': [round(v, 4) for v in df['open']],
        'close': [round(v, 4) for v in df['close']],
        'high': [round(v, 4) for v in df['high']],
        'low': [round(v, 4) for v in df['low']],
        'volume': [int(v) for v in df['volume']],
        'ma_50': [round(v, 4) if pd.notna(v) else None for v in df['ma_50']],
        'ma_150': [round(v, 4) if pd.notna(v) else None for v in df['ma_150']],
        'ma_200': [round(v, 4) if pd.notna(v) else None for v in df['ma_200']],
    })


if __name__ == '__main__':
    # Auto-update prices if stale (>16 hours old)
    from data_manager import auto_update_if_stale
    try:
        auto_update_if_stale(max_age_hours=16)
    except Exception as e:
        print(f"  Auto-update skipped: {e}")

    app.run(debug=True, port=5001, use_reloader=True, reloader_type='stat')
