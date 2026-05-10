"""
MKTT — Matej Krajcovic Trading Tool
Flask web application
"""
from flask import Flask, render_template, request, jsonify
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
# PCA / Stage / EPS classification lookups
# =========================================================================
_classification_cache = {'data': None}

def load_classification_lookups():
    """Load pre-computed PCA, stage, and EPS accel/decel classifications."""
    if _classification_cache['data'] is not None:
        return _classification_cache['data']

    import json
    from pathlib import Path
    data_dir = Path(__file__).parent.parent.parent / 'sandbox' / 'analysis' / 'stage_pca' / 'output' / 'data'

    lookups = {}

    # PCA-20 regimes: symbol -> regime name
    try:
        with open(data_dir / 'pca20_5c_meta.json') as f:
            d = json.load(f)
        pca = {}
        for k, v in d.items():
            for st in v['stocks']:
                pca[st['s']] = v['n']
        lookups['pca20'] = pca
        lookups['pca20_labels'] = sorted(set(pca.values()))
    except:
        lookups['pca20'] = {}
        lookups['pca20_labels'] = []

    # Weinstein stages: symbol -> stage label
    try:
        with open(data_dir / 'stages_meta.json') as f:
            d = json.load(f)
        stages = {}
        for k, v in d.items():
            for st in v['stocks']:
                stages[st['s']] = v['n']
        lookups['stages'] = stages
        lookups['stage_labels'] = sorted(set(stages.values()))
    except:
        lookups['stages'] = {}
        lookups['stage_labels'] = []

    # EPS acceleration: symbol -> 'Accelerating' or 'Decelerating'
    try:
        with open(data_dir / 'eps_growth_meta.json') as f:
            d = json.load(f)
        eps_acc = {}
        for k, v in d.get('accel', {}).items():
            for st in v['stocks']:
                eps_acc[st['s']] = {'label': 'Accelerating' if k == '1' else 'Decelerating',
                                    'acc': st.get('acc'), 'g1': st.get('g1'), 'g2': st.get('g2')}
        lookups['eps_accel'] = eps_acc
    except:
        lookups['eps_accel'] = {}

    # MA Screener: symbol -> category
    try:
        with open(data_dir / 'screener_meta.json') as f:
            d = json.load(f)
        ma_screen = {}
        for k, v in d.items():
            for st in v['stocks']:
                ma_screen[st['s']] = v['n']
        lookups['ma_screen'] = ma_screen
        lookups['ma_screen_labels'] = sorted(set(ma_screen.values()))
    except:
        lookups['ma_screen'] = {}
        lookups['ma_screen_labels'] = []

    _classification_cache['data'] = lookups
    return lookups


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
                rec['fy1_rev'] = _safe_num(f1.iloc[0].get('Revenue - Mean'))
                rec['fy2_eps'] = None
                rec['fy2_rev'] = None
        if fy2 is not None:
            f2 = fy2[fy2['Symbol'] == sym]
            if len(f2) > 0:
                rec['fy2_eps'] = _safe_num(f2.iloc[0].get('Earnings Per Share - Mean'))
                rec['fy2_rev'] = _safe_num(f2.iloc[0].get('Revenue - Mean'))
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

    # Fundamental filters
    def _flt(name):
        v = request.args.get(name, '')
        if v == '': return None
        try: return float(v)
        except: return None

    pe_min = _flt('pe_min')
    pe_max = _flt('pe_max')
    fwdpe_min = _flt('fwdpe_min')
    fwdpe_max = _flt('fwdpe_max')
    opmgn_min = _flt('opmgn_min')
    opmgn_max = _flt('opmgn_max')
    roic_min = _flt('roic_min')
    roic_max = _flt('roic_max')
    evebitda_min = _flt('evebitda_min')
    evebitda_max = _flt('evebitda_max')
    ndebitda_min = _flt('ndebitda_min')
    ndebitda_max = _flt('ndebitda_max')
    rs_min = _flt('rs_min')
    analysts_min = _flt('analysts_min')
    eps_growth = request.args.get('eps_growth', '')
    rev_growth = request.args.get('rev_growth', '')
    eps_accel_filt = request.args.get('eps_accel_filter', '')
    pe_sect_min = _flt('pe_sect_min')
    pe_sect_max = _flt('pe_sect_max')
    pe_ind_min = _flt('pe_ind_min')
    pe_ind_max = _flt('pe_ind_max')

    # Classification filters (multi-select)
    pca_regime = request.args.getlist('pca_regime')
    stage_filter = request.args.getlist('stage_class')
    eps_accel_filter = request.args.getlist('eps_accel')
    ma_screen_filter = request.args.getlist('ma_screen')

    # Technical filters
    pct50_min = _flt('pct50_min')
    pct50_max = _flt('pct50_max')
    pct200_min = _flt('pct200_min')
    pct200_max = _flt('pct200_max')
    from52h_min = _flt('from52h_min')
    from52h_max = _flt('from52h_max')
    from52l_min = _flt('from52l_min')
    ma_setup = request.args.get('ma_setup', '')
    rschg1w_min = _flt('rschg1w_min')
    rschg1w_max = _flt('rschg1w_max')
    rschg1m_min = _flt('rschg1m_min')
    rschg1m_max = _flt('rschg1m_max')
    rschg3m_min = _flt('rschg3m_min')
    rschg3m_max = _flt('rschg3m_max')

    has_fund_filters = any(x is not None for x in [
        pe_min, pe_max, fwdpe_min, fwdpe_max, opmgn_min, opmgn_max,
        roic_min, roic_max, evebitda_min, evebitda_max, ndebitda_min, ndebitda_max,
        rs_min, analysts_min, pe_sect_min, pe_sect_max, pe_ind_min, pe_ind_max]) or eps_growth != '' or rev_growth != '' or eps_accel_filt != ''

    has_tech_filters = any(x is not None for x in [
        pct50_min, pct50_max, pct200_min, pct200_max,
        from52h_min, from52h_max, from52l_min,
        rschg1w_min, rschg1w_max, rschg1m_min, rschg1m_max,
        rschg3m_min, rschg3m_max]) or ma_setup != ''

    has_class_filters = any(len(x) > 0 for x in [pca_regime, stage_filter, eps_accel_filter, ma_screen_filter])

    filters = {
        'preset': preset,
        'min_turnover': min_turnover,
        'sector': sector,
        'min_price': min_price,
        'sort_by': sort_by,
        'as_of': request.args.get('as_of', ''),
        'pe_min': pe_min, 'pe_max': pe_max,
        'fwdpe_min': fwdpe_min, 'fwdpe_max': fwdpe_max,
        'opmgn_min': opmgn_min, 'opmgn_max': opmgn_max,
        'roic_min': roic_min, 'roic_max': roic_max,
        'evebitda_min': evebitda_min, 'evebitda_max': evebitda_max,
        'ndebitda_min': ndebitda_min, 'ndebitda_max': ndebitda_max,
        'pe_sect_min': pe_sect_min, 'pe_sect_max': pe_sect_max,
        'pe_ind_min': pe_ind_min, 'pe_ind_max': pe_ind_max,
        'rs_min': rs_min, 'analysts_min': analysts_min,
        'eps_growth': eps_growth,
        'rev_growth': rev_growth,
        'eps_accel_filter': eps_accel_filt,
        'has_fund_filters': has_fund_filters,
        'pct50_min': pct50_min, 'pct50_max': pct50_max,
        'pct200_min': pct200_min, 'pct200_max': pct200_max,
        'from52h_min': from52h_min, 'from52h_max': from52h_max,
        'from52l_min': from52l_min,
        'ma_setup': ma_setup,
        'rschg1w_min': rschg1w_min, 'rschg1w_max': rschg1w_max,
        'rschg1m_min': rschg1m_min, 'rschg1m_max': rschg1m_max,
        'rschg3m_min': rschg3m_min, 'rschg3m_max': rschg3m_max,
        'has_tech_filters': has_tech_filters,
        'pca_regime': pca_regime,
        'stage_class': stage_filter,
        'eps_accel': eps_accel_filter,
        'ma_screen': ma_screen_filter,
        'has_class_filters': has_class_filters,
    }

    start = time.time()
    stage_dist = None
    market_regime = None
    universe_total = 0
    sectors = []
    _as_of_label = ''

    if preset == 'all':
        # Plain screener — use local Parquet DB + Refinitiv enrichment (no yfinance API call)
        from data_manager import load_prices, load_universe
        close = load_prices('close')
        uni = load_universe()
        rfv = load_refinitiv_snapshot()

        if close is not None and not close.empty:
            # Select trading date (query param or latest with substantial data)
            as_of_date = request.args.get('as_of', '')
            min_stocks = len(close.columns) * 0.5
            if as_of_date:
                # Find the exact or nearest prior date
                target = pd.Timestamp(as_of_date)
                valid_dates = close.index[close.index <= target]
                if len(valid_dates) > 0:
                    _idx = close.index.get_loc(valid_dates[-1])
                else:
                    _idx = 0
            else:
                # Default: find last row with >50% data
                _idx = len(close) - 1
                for _i in range(len(close) - 1, max(len(close) - 10, 0), -1):
                    if close.iloc[_i].notna().sum() >= min_stocks:
                        _idx = _i
                        break
            _as_of_label = str(close.index[_idx])[:10]
            last_prices = close.iloc[_idx]
            prev_prices = close.iloc[_idx - 1] if _idx > 0 else last_prices

            # Compute technicals vectorized (using data up to _idx)
            _close_slice = close.iloc[:_idx + 1]
            ma50 = _close_slice.rolling(50).mean().iloc[-1]
            ma150 = _close_slice.rolling(150).mean().iloc[-1]
            ma200 = _close_slice.rolling(200).mean().iloc[-1]
            high_52w = _close_slice.iloc[-252:].max() if len(_close_slice) >= 252 else _close_slice.max()
            low_52w = _close_slice.iloc[-252:].min() if len(_close_slice) >= 252 else _close_slice.min()

            # RS rank (6-month return percentile) — current and historical for delta
            rs_ranks = {}
            rs_1w = {}
            rs_1m = {}
            rs_3m = {}
            if len(_close_slice) > 126:
                ret_6m = (_close_slice.iloc[-1] / _close_slice.iloc[-126] - 1)
                rs_pct = ret_6m.rank(pct=True) * 100
                rs_ranks = rs_pct.to_dict()

                # RS at 1 week ago (5 trading days)
                if len(_close_slice) > 131:
                    s = _close_slice.iloc[:-5]
                    r6 = (s.iloc[-1] / s.iloc[-126] - 1)
                    rs_1w = (r6.rank(pct=True) * 100).to_dict()

                # RS at 1 month ago (~21 trading days)
                if len(_close_slice) > 147:
                    s = _close_slice.iloc[:-21]
                    r6 = (s.iloc[-1] / s.iloc[-126] - 1)
                    rs_1m = (r6.rank(pct=True) * 100).to_dict()

                # RS at 3 months ago (~63 trading days)
                if len(_close_slice) > 189:
                    s = _close_slice.iloc[:-63]
                    r6 = (s.iloc[-1] / s.iloc[-126] - 1)
                    rs_3m = (r6.rank(pct=True) * 100).to_dict()

            rows = []
            for sym in close.columns:
                price = last_prices.get(sym)
                prev = prev_prices.get(sym)
                if pd.isna(price) or price <= 0:
                    continue
                if price < min_price:
                    continue

                uni_row = uni[uni['symbol'] == sym].iloc[0] if uni is not None and sym in uni['symbol'].values else None
                turnover = float(uni_row['turnover']) if uni_row is not None and pd.notna(uni_row.get('turnover')) else 0
                if turnover < min_turnover:
                    continue

                r = rfv.get(sym, {})
                sec_name = r.get('sector', '')
                if not sec_name:
                    continue
                if sector and sector != 'All' and sec_name != sector:
                    continue

                change_pct = ((price / prev) - 1) * 100 if pd.notna(prev) and prev > 0 else 0

                # Technical values
                m50 = ma50.get(sym)
                m150 = ma150.get(sym)
                m200 = ma200.get(sym)
                h52 = high_52w.get(sym)
                l52 = low_52w.get(sym)

                pct_above_50 = ((price / m50) - 1) * 100 if pd.notna(m50) and m50 > 0 else None
                pct_above_200 = ((price / m200) - 1) * 100 if pd.notna(m200) and m200 > 0 else None
                from_52h = ((price / h52) - 1) * 100 if pd.notna(h52) and h52 > 0 else None
                from_52l = ((price / l52) - 1) * 100 if pd.notna(l52) and l52 > 0 else None

                rows.append({
                    'Symbol': sym,
                    'Price': round(float(price), 2),
                    'Change%': round(float(change_pct), 2),
                    'Sector': sec_name,
                    'Industry': r.get('industry', ''),
                    'ADV_Dollar': turnover,
                    'RS_Rank': round(rs_ranks.get(sym, 0), 0) if sym in rs_ranks else None,
                    'RS_Chg1W': round(rs_ranks.get(sym, 0) - rs_1w.get(sym, 0), 1) if sym in rs_ranks and sym in rs_1w else None,
                    'RS_Chg1M': round(rs_ranks.get(sym, 0) - rs_1m.get(sym, 0), 1) if sym in rs_ranks and sym in rs_1m else None,
                    'RS_Chg3M': round(rs_ranks.get(sym, 0) - rs_3m.get(sym, 0), 1) if sym in rs_ranks and sym in rs_3m else None,
                    'MA50': round(float(m50), 2) if pd.notna(m50) else None,
                    'MA150': round(float(m150), 2) if pd.notna(m150) else None,
                    'MA200': round(float(m200), 2) if pd.notna(m200) else None,
                    'PctAbove50': round(float(pct_above_50), 1) if pct_above_50 is not None else None,
                    'PctAbove200': round(float(pct_above_200), 1) if pct_above_200 is not None else None,
                    'From52H': round(float(from_52h), 1) if from_52h is not None else None,
                    'From52L': round(float(from_52l), 1) if from_52l is not None else None,
                })

            df = pd.DataFrame(rows)
            if not df.empty:
                sort_col_map = {
                    'turnover': ('ADV_Dollar', False), 'change': ('Change%', False),
                    'rs': ('RS_Rank', False), 'pe': ('PE', True), 'fwdpe': ('FwdPE', True),
                    'opmgn': ('OpMargin', False), 'roic': ('ROIC', False), 'evebitda': ('EV_EBITDA', True),
                }
                sc, asc_default = sort_col_map.get(sort_by, ('ADV_Dollar', False))
                if sc in df.columns:
                    df = df.sort_values(sc, ascending=asc_default, na_position='last')
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
                    'pe': ('PE', True),
                    'fwdpe': ('FwdPE', True),
                    'opmgn': ('OpMargin', False),
                    'roic': ('ROIC', False),
                    'evebitda': ('EV_EBITDA', True),
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
                             ('Rev_Act', 'rev_act'), ('Rev_FY1', 'fy1_rev'), ('Rev_FY2', 'fy2_rev'),
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

        # Compute PE premium vs sector/industry medians (using FULL universe, not filtered)
        if rfv and 'PE' in results_df.columns:
            # Build full universe PE by sector/industry from Refinitiv data
            _all_pe = []
            from data_manager import load_prices
            _close = load_prices('close')
            if _close is not None:
                # Use same date as main screener (last_prices already computed above)
                _last = last_prices
                for sym, rec in rfv.items():
                    eps = rec.get('eps_act')
                    price = _last.get(sym)
                    if eps and eps > 0 and pd.notna(price) and price > 0:
                        _all_pe.append({'sector': rec.get('sector'), 'industry': rec.get('industry'), 'pe': float(price) / float(eps)})
                if _all_pe:
                    _pe_df = pd.DataFrame(_all_pe)
                    _sector_median_pe = _pe_df.groupby('sector')['pe'].median().to_dict()
                    _industry_median_pe = _pe_df.groupby('industry')['pe'].median().to_dict()
                else:
                    _sector_median_pe = {}
                    _industry_median_pe = {}
            else:
                _sector_median_pe = {}
                _industry_median_pe = {}

            # Compute ratio: stock PE / sector median PE
            def _pe_prem_sector(row):
                pe = row.get('PE')
                sec = row.get('Sector')
                if pd.isna(pe) or pe is None or not sec:
                    return None
                med = _sector_median_pe.get(sec)
                if not med or med <= 0:
                    return None
                return round(float(pe) / med, 2)

            def _pe_prem_industry(row):
                pe = row.get('PE')
                ind = row.get('Industry')
                if pd.isna(pe) or pe is None or not ind:
                    return None
                med = _industry_median_pe.get(ind)
                if not med or med <= 0:
                    return None
                return round(float(pe) / med, 2)

            results_df['PE_vs_Sector'] = results_df.apply(_pe_prem_sector, axis=1)
            results_df['PE_vs_Industry'] = results_df.apply(_pe_prem_industry, axis=1)

        # Compute EPS growth metrics from quarterly data
        if rfv:
            import pickle
            from pathlib import Path
            _pkl = Path(__file__).parent.parent.parent / 'data' / 'mktt' / 'refinitiv_fundamentals.pkl'
            _qdata = None
            _pkl_data = {}
            if _pkl.exists():
                try:
                    with open(_pkl, 'rb') as f:
                        _pkl_data = pickle.load(f)
                    _qdata = _pkl_data.get('quarterly')
                except:
                    pass

            if _qdata is not None:
                _qdata['Date'] = pd.to_datetime(_qdata['Date'], errors='coerce')
                _qdata['EPS'] = pd.to_numeric(_qdata['Earnings Per Share - Actual'], errors='coerce')
                _q_valid = _qdata.dropna(subset=['EPS', 'Date'])

                # Pre-compute per-symbol: TTM, prior TTM, latest FQ, same FQ year ago
                _eps_metrics = {}
                for sym, grp in _q_valid.groupby('Symbol'):
                    grp = grp.sort_values('Date')
                    eps_vals = grp['EPS'].values
                    n = len(eps_vals)
                    if n >= 4:
                        ttm = eps_vals[-4:].sum()
                        prior_ttm = eps_vals[-8:-4].sum() if n >= 8 else None
                        fq_latest = eps_vals[-1]
                        fq_yoy = eps_vals[-5] if n >= 5 else None
                        _eps_metrics[sym] = {
                            'ttm': ttm, 'prior_ttm': prior_ttm,
                            'fq_latest': fq_latest, 'fq_yoy': fq_yoy,
                        }

                # Compute growth columns
                def _g_ntm_ttm(row):
                    ntm = row.get('EPS_NTM')
                    ttm = row.get('EPS_TTM')
                    if pd.notna(ntm) and pd.notna(ttm) and ttm and ttm != 0:
                        return round((float(ntm) / float(ttm) - 1) * 100, 1)
                    return None

                def _g_fy2_fy1(row):
                    fy1 = row.get('EPS_FY1')
                    fy2 = row.get('EPS_FY2')
                    if pd.notna(fy1) and pd.notna(fy2) and fy1 != 0:
                        return round((float(fy2) / float(fy1) - 1) * 100, 1)
                    return None

                def _g_ttm_yoy(sym):
                    m = _eps_metrics.get(sym)
                    if m and m['prior_ttm'] and m['prior_ttm'] != 0:
                        return round((m['ttm'] / m['prior_ttm'] - 1) * 100, 1)
                    return None

                def _g_fq_yoy(sym):
                    m = _eps_metrics.get(sym)
                    if m and m['fq_yoy'] and m['fq_yoy'] != 0:
                        return round((m['fq_latest'] / m['fq_yoy'] - 1) * 100, 1)
                    return None

                # True NTM: sum of next 4 quarterly estimates from forward_quarterly
                _fwd_q = _pkl_data.get('forward_quarterly')
                _ntm_eps = {}
                _ntm_rev = {}
                if _fwd_q is not None:
                    for sym, grp in _fwd_q.groupby('Symbol'):
                        eps_vals = pd.to_numeric(grp['Earnings Per Share - Mean'], errors='coerce').dropna()
                        rev_vals = pd.to_numeric(grp['Revenue - Mean'], errors='coerce').dropna()
                        if len(eps_vals) >= 4:
                            _ntm_eps[sym] = round(float(eps_vals.iloc[:4].sum()), 2)
                        if len(rev_vals) >= 4:
                            _ntm_rev[sym] = round(float(rev_vals.iloc[:4].sum() / 1e6), 1)

                # TTM / NTM absolute values
                results_df['EPS_TTM'] = results_df['Symbol'].map(
                    lambda s: round(_eps_metrics[s]['ttm'], 2) if s in _eps_metrics else None)
                results_df['EPS_NTM'] = results_df['Symbol'].map(lambda s: _ntm_eps.get(s))

                # Growth: NTM vs TTM (using true NTM from forward quarterly)
                def _g_ntm_ttm(sym):
                    ntm = _ntm_eps.get(sym)
                    m = _eps_metrics.get(sym)
                    if ntm and m and m['ttm'] and m['ttm'] != 0:
                        return round((ntm / m['ttm'] - 1) * 100, 1)
                    return None

                results_df['G_NTM_TTM'] = results_df['Symbol'].map(_g_ntm_ttm)
                results_df['G_FY2_FY1'] = results_df.apply(_g_fy2_fy1, axis=1)
                results_df['G_TTM_YOY'] = results_df['Symbol'].map(_g_ttm_yoy)
                results_df['G_FQ_YOY'] = results_df['Symbol'].map(_g_fq_yoy)

                # Revenue growth metrics (same logic, different columns)
                _rev_metrics = {}
                _qr_valid = _qdata.copy()
                _qr_valid['Rev'] = pd.to_numeric(_qr_valid['Revenue - Actual'], errors='coerce')
                _qr_valid = _qr_valid.dropna(subset=['Rev', 'Date'])
                for sym, grp in _qr_valid.groupby('Symbol'):
                    grp = grp.sort_values('Date')
                    rv = grp['Rev'].values
                    n = len(rv)
                    if n >= 4:
                        ttm = rv[-4:].sum()
                        prior_ttm = rv[-8:-4].sum() if n >= 8 else None
                        fq_latest = rv[-1]
                        fq_yoy = rv[-5] if n >= 5 else None
                        _rev_metrics[sym] = {
                            'ttm': ttm, 'prior_ttm': prior_ttm,
                            'fq_latest': fq_latest, 'fq_yoy': fq_yoy,
                        }

                def _rg_ntm_ttm(row):
                    ntm = row.get('Rev_NTM')
                    ttm = row.get('Rev_TTM')
                    if pd.notna(ntm) and pd.notna(ttm) and ttm and ttm != 0:
                        return round((float(ntm) / float(ttm) - 1) * 100, 1)
                    return None

                def _rg_fy2_fy1(row):
                    fy1 = row.get('Rev_FY1')
                    fy2 = row.get('Rev_FY2')
                    if pd.notna(fy1) and pd.notna(fy2) and fy1 and fy1 != 0:
                        return round((float(fy2) / float(fy1) - 1) * 100, 1)
                    return None

                def _rg_ttm_yoy(sym):
                    m = _rev_metrics.get(sym)
                    if m and m['prior_ttm'] and m['prior_ttm'] != 0:
                        return round((m['ttm'] / m['prior_ttm'] - 1) * 100, 1)
                    return None

                def _rg_fq_yoy(sym):
                    m = _rev_metrics.get(sym)
                    if m and m['fq_yoy'] and m['fq_yoy'] != 0:
                        return round((m['fq_latest'] / m['fq_yoy'] - 1) * 100, 1)
                    return None

                results_df['RG_NTM_TTM'] = results_df.apply(_rg_ntm_ttm, axis=1)
                results_df['RG_FY2_FY1'] = results_df.apply(_rg_fy2_fy1, axis=1)
                results_df['RG_TTM_YOY'] = results_df['Symbol'].map(_rg_ttm_yoy)
                results_df['RG_FQ_YOY'] = results_df['Symbol'].map(_rg_fq_yoy)

                # Revenue TTM / NTM absolute values
                results_df['Rev_TTM'] = results_df['Symbol'].map(
                    lambda s: round(_rev_metrics[s]['ttm'] / 1e6, 1) if s in _rev_metrics else None)
                results_df['Rev_NTM'] = results_df['Symbol'].map(lambda s: _ntm_rev.get(s))

        # Write enriched data back
        enrich_cols = ['Sector', 'Industry', 'PE', 'FwdPE',
                       'EPS_Act', 'EPS_FY1', 'EPS_FY2', 'Rev_Act', 'Rev_FY1', 'Rev_FY2',
                       'OpMargin', 'NetMargin',
                       'FCF', 'ROIC', 'ND_EBITDA', 'EV_EBITDA', 'Target', 'Analysts',
                       'PCA_Regime', 'Stage_Class', 'EPS_Accel', 'EPS_Acc_Val', 'MA_Screen',
                       'PE_vs_Sector', 'PE_vs_Industry',
                       'EPS_TTM', 'EPS_NTM', 'Rev_TTM', 'Rev_NTM',
                       'G_NTM_TTM', 'G_FY2_FY1', 'G_TTM_YOY', 'G_FQ_YOY',
                       'RG_NTM_TTM', 'RG_FY2_FY1', 'RG_TTM_YOY', 'RG_FQ_YOY']

        # Enrich with PCA/Stage/EPS classifications
        cls = load_classification_lookups()
        if cls.get('pca20'):
            results_df['PCA_Regime'] = results_df['Symbol'].map(cls['pca20'])
        if cls.get('stages'):
            results_df['Stage_Class'] = results_df['Symbol'].map(cls['stages'])
        if cls.get('eps_accel'):
            results_df['EPS_Accel'] = results_df['Symbol'].map(
                lambda s: cls['eps_accel'].get(s, {}).get('label') if isinstance(cls['eps_accel'].get(s), dict) else None)
            results_df['EPS_Acc_Val'] = results_df['Symbol'].map(
                lambda s: cls['eps_accel'].get(s, {}).get('acc') if isinstance(cls['eps_accel'].get(s), dict) else None)
        if cls.get('ma_screen'):
            results_df['MA_Screen'] = results_df['Symbol'].map(cls['ma_screen'])

        # Save full enriched df for sector/industry medians (before any filtering)
        _full_df = results_df.copy()

        # Apply classification filters
        if has_class_filters:
            if pca_regime and 'PCA_Regime' in results_df.columns:
                results_df = results_df[results_df['PCA_Regime'].isin(pca_regime)]
            if stage_filter and 'Stage_Class' in results_df.columns:
                results_df = results_df[results_df['Stage_Class'].isin(stage_filter)]
            if eps_accel_filter and 'EPS_Accel' in results_df.columns:
                results_df = results_df[results_df['EPS_Accel'].isin(eps_accel_filter)]
            if ma_screen_filter and 'MA_Screen' in results_df.columns:
                results_df = results_df[results_df['MA_Screen'].isin(ma_screen_filter)]
            data = results_df.to_dict('records')

        # Apply fundamental filters BEFORE building sector stats
        def _range_filter(df, col, vmin, vmax):
            vals = pd.to_numeric(df[col], errors='coerce') if col in df.columns else pd.Series(dtype=float)
            if vmin is not None:
                df = df[vals >= vmin]
                vals = vals.loc[df.index]
            if vmax is not None:
                df = df[vals <= vmax]
            return df

        if has_fund_filters:
            results_df = _range_filter(results_df, 'PE', pe_min, pe_max)
            results_df = _range_filter(results_df, 'FwdPE', fwdpe_min, fwdpe_max)
            results_df = _range_filter(results_df, 'OpMargin', opmgn_min, opmgn_max)
            results_df = _range_filter(results_df, 'ROIC', roic_min, roic_max)
            results_df = _range_filter(results_df, 'EV_EBITDA', evebitda_min, evebitda_max)
            results_df = _range_filter(results_df, 'ND_EBITDA', ndebitda_min, ndebitda_max)
            results_df = _range_filter(results_df, 'PE_vs_Sector', pe_sect_min, pe_sect_max)
            results_df = _range_filter(results_df, 'PE_vs_Industry', pe_ind_min, pe_ind_max)
            results_df = _range_filter(results_df, 'RS_Rank', rs_min, None)
            results_df = _range_filter(results_df, 'Analysts', analysts_min, None)

            # EPS growth filters
            _gc = lambda col: pd.to_numeric(results_df[col], errors='coerce') if col in results_df.columns else pd.Series(dtype=float)
            if eps_growth == 'ntm_pos':
                results_df = results_df[_gc('G_NTM_TTM') > 0]
            elif eps_growth == 'ntm_neg':
                results_df = results_df[_gc('G_NTM_TTM') < 0]
            elif eps_growth == 'fy2_fy1_pos':
                results_df = results_df[_gc('G_FY2_FY1') > 0]
            elif eps_growth == 'fy2_fy1_neg':
                results_df = results_df[_gc('G_FY2_FY1') < 0]
            elif eps_growth == 'ttm_yoy_pos':
                results_df = results_df[_gc('G_TTM_YOY') > 0]
            elif eps_growth == 'ttm_yoy_neg':
                results_df = results_df[_gc('G_TTM_YOY') < 0]
            elif eps_growth == 'fq_yoy_pos':
                results_df = results_df[_gc('G_FQ_YOY') > 0]
            elif eps_growth == 'fq_yoy_neg':
                results_df = results_df[_gc('G_FQ_YOY') < 0]
            elif eps_growth == 'all_pos':
                results_df = results_df[(_gc('G_NTM_TTM') > 0) & (_gc('G_FY2_FY1') > 0)]

            # Revenue growth filters
            if rev_growth == 'ntm_pos':
                results_df = results_df[_gc('RG_NTM_TTM') > 0]
            elif rev_growth == 'ntm_neg':
                results_df = results_df[_gc('RG_NTM_TTM') < 0]
            elif rev_growth == 'fy2_fy1_pos':
                results_df = results_df[_gc('RG_FY2_FY1') > 0]
            elif rev_growth == 'fy2_fy1_neg':
                results_df = results_df[_gc('RG_FY2_FY1') < 0]
            elif rev_growth == 'ttm_yoy_pos':
                results_df = results_df[_gc('RG_TTM_YOY') > 0]
            elif rev_growth == 'ttm_yoy_neg':
                results_df = results_df[_gc('RG_TTM_YOY') < 0]
            elif rev_growth == 'fq_yoy_pos':
                results_df = results_df[_gc('RG_FQ_YOY') > 0]
            elif rev_growth == 'fq_yoy_neg':
                results_df = results_df[_gc('RG_FQ_YOY') < 0]
            elif rev_growth == 'all_pos':
                results_df = results_df[(_gc('RG_NTM_TTM') > 0) & (_gc('RG_FY2_FY1') > 0)]

            # EPS Acceleration filter
            if eps_accel_filt == 'accel':
                results_df = results_df[_gc('G_NTM_TTM') > _gc('G_TTM_YOY')]
            elif eps_accel_filt == 'decel':
                results_df = results_df[_gc('G_NTM_TTM') < _gc('G_TTM_YOY')]
            elif eps_accel_filt == 'accel_pos':
                results_df = results_df[(_gc('G_NTM_TTM') > _gc('G_TTM_YOY')) & (_gc('G_NTM_TTM') > 0) & (_gc('G_TTM_YOY') > 0)]
            elif eps_accel_filt == 'decel_neg':
                results_df = results_df[(_gc('G_NTM_TTM') < _gc('G_TTM_YOY')) & (_gc('G_NTM_TTM') < 0)]

            # Rebuild data list after filtering
            data = results_df.to_dict('records')

        # Apply technical filters
        if has_tech_filters:
            results_df = _range_filter(results_df, 'PctAbove50', pct50_min, pct50_max)
            results_df = _range_filter(results_df, 'PctAbove200', pct200_min, pct200_max)
            results_df = _range_filter(results_df, 'From52H', from52h_min, from52h_max)
            results_df = _range_filter(results_df, 'From52L', from52l_min, None)
            results_df = _range_filter(results_df, 'RS_Chg1W', rschg1w_min, rschg1w_max)
            results_df = _range_filter(results_df, 'RS_Chg1M', rschg1m_min, rschg1m_max)
            results_df = _range_filter(results_df, 'RS_Chg3M', rschg3m_min, rschg3m_max)

            if ma_setup == 'above_all' and all(c in results_df.columns for c in ['Price','MA50','MA150','MA200']):
                results_df = results_df[
                    (pd.to_numeric(results_df['Price'], errors='coerce') > pd.to_numeric(results_df['MA50'], errors='coerce')) &
                    (pd.to_numeric(results_df['Price'], errors='coerce') > pd.to_numeric(results_df['MA150'], errors='coerce')) &
                    (pd.to_numeric(results_df['Price'], errors='coerce') > pd.to_numeric(results_df['MA200'], errors='coerce'))
                ]
            elif ma_setup == 'above_50' and all(c in results_df.columns for c in ['Price','MA50']):
                results_df = results_df[pd.to_numeric(results_df['Price'], errors='coerce') > pd.to_numeric(results_df['MA50'], errors='coerce')]
            elif ma_setup == 'below_50' and all(c in results_df.columns for c in ['Price','MA50']):
                results_df = results_df[pd.to_numeric(results_df['Price'], errors='coerce') < pd.to_numeric(results_df['MA50'], errors='coerce')]
            elif ma_setup == 'below_all' and all(c in results_df.columns for c in ['Price','MA50','MA150','MA200']):
                results_df = results_df[
                    (pd.to_numeric(results_df['Price'], errors='coerce') < pd.to_numeric(results_df['MA50'], errors='coerce')) &
                    (pd.to_numeric(results_df['Price'], errors='coerce') < pd.to_numeric(results_df['MA150'], errors='coerce')) &
                    (pd.to_numeric(results_df['Price'], errors='coerce') < pd.to_numeric(results_df['MA200'], errors='coerce'))
                ]
            elif ma_setup == 'golden_cross' and all(c in results_df.columns for c in ['MA50','MA200']):
                results_df = results_df[
                    (pd.to_numeric(results_df['MA50'], errors='coerce') > pd.to_numeric(results_df['MA200'], errors='coerce'))
                ]
            elif ma_setup == 'death_cross' and all(c in results_df.columns for c in ['MA50','MA200']):
                results_df = results_df[
                    (pd.to_numeric(results_df['MA50'], errors='coerce') < pd.to_numeric(results_df['MA200'], errors='coerce'))
                ]
            elif ma_setup == 'stacked_bull' and all(c in results_df.columns for c in ['MA50','MA150','MA200']):
                results_df = results_df[
                    (pd.to_numeric(results_df['MA50'], errors='coerce') > pd.to_numeric(results_df['MA150'], errors='coerce')) &
                    (pd.to_numeric(results_df['MA150'], errors='coerce') > pd.to_numeric(results_df['MA200'], errors='coerce'))
                ]

            data = results_df.to_dict('records')

        # Write enriched data back
        for i in range(len(data)):
            for col in enrich_cols:
                if col in results_df.columns:
                    idx = results_df.index[i] if i < len(results_df) else None
                    if idx is not None:
                        val = results_df.loc[idx, col] if col in results_df.columns else None
                        data[i][col] = val if pd.notna(val) else None

        pe_col = 'PE' if 'PE' in results_df.columns else None
        fwdpe_col = 'FwdPE' if 'FwdPE' in results_df.columns else None

        if 'Sector' in results_df.columns:
            # Use full (unfiltered) df for medians, filtered df for stock lists
            _full_grouped = _full_df.groupby('Sector') if '_full_df' in dir() else None
            grouped = results_df.groupby('Sector')
            for sector_name, group in grouped:
                if not sector_name or pd.isna(sector_name):
                    continue

                # Full sector group for medians (all stocks regardless of filter)
                full_group = _full_grouped.get_group(sector_name) if _full_grouped and sector_name in _full_grouped.groups else group

                total_in_sector = sector_totals.get(sector_name, len(full_group))
                stats = {
                    'sector': sector_name,
                    'count': len(group),
                    'total': total_in_sector,
                    'pct_of_sector': len(group) / total_in_sector * 100 if total_in_sector > 0 else 0,
                    'pct_of_results': len(group) / len(results_df) * 100,
                }
                def _median_of(col_name, positive_only=False):
                    if col_name not in full_group.columns:
                        return None
                    vals = pd.to_numeric(full_group[col_name], errors='coerce').dropna()
                    if positive_only:
                        vals = vals[vals > 0]
                    return float(vals.median()) if len(vals) > 0 else None

                stats['median_pe'] = _median_of('PE', positive_only=True)
                stats['median_fwd_pe'] = _median_of('FwdPE', positive_only=True)
                stats['median_eps'] = _median_of('EPS_Act')
                stats['median_eps_ttm'] = _median_of('EPS_TTM')
                stats['median_eps_ntm'] = _median_of('EPS_NTM')
                stats['median_fy1'] = _median_of('EPS_FY1')
                stats['median_fy2'] = _median_of('EPS_FY2')
                stats['median_rev_ttm'] = _median_of('Rev_TTM')
                stats['median_rev_ntm'] = _median_of('Rev_NTM')
                stats['median_op_margin'] = _median_of('OpMargin')
                stats['median_net_margin'] = _median_of('NetMargin')
                stats['median_roic'] = _median_of('ROIC')
                stats['median_fcf'] = _median_of('FCF')
                stats['median_nd_ebitda'] = _median_of('ND_EBITDA')
                stats['median_ev_ebitda'] = _median_of('EV_EBITDA', positive_only=True)
                def _mean_of(col_name):
                    if col_name not in group.columns:
                        return None
                    vals = pd.to_numeric(group[col_name], errors='coerce').dropna()
                    return float(vals.mean()) if len(vals) > 0 else None

                stats['median_rs'] = _median_of('RS_Rank')
                stats['median_rs_chg1w'] = _mean_of('RS_Chg1W')
                stats['median_rs_chg1m'] = _mean_of('RS_Chg1M')
                stats['median_rs_chg3m'] = _mean_of('RS_Chg3M')
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
                        'pe_vs_sector': _g('PE_vs_Sector'),
                        'pe_vs_industry': _g('PE_vs_Industry'),
                        'rs_rank': _g('RS_Rank'),
                        'rs_chg1w': _g('RS_Chg1W'),
                        'rs_chg1m': _g('RS_Chg1M'),
                        'rs_chg3m': _g('RS_Chg3M'),
                        'g_ntm_ttm': _g('G_NTM_TTM'),
                        'g_fy2_fy1': _g('G_FY2_FY1'),
                        'g_ttm_yoy': _g('G_TTM_YOY'),
                        'g_fq_yoy': _g('G_FQ_YOY'),
                        'mansfield': _g('Mansfield_RS'),
                        'industry': _g('Industry') or '',
                        'eps_act': _g('EPS_Act'),
                        'eps_ttm': _g('EPS_TTM'),
                        'eps_ntm': _g('EPS_NTM'),
                        'eps_fy1': _g('EPS_FY1'),
                        'eps_fy2': _g('EPS_FY2'),
                        'rev_ttm': _g('Rev_TTM'),
                        'rev_ntm': _g('Rev_NTM'),
                        'rev_fy1': _g('Rev_FY1'),
                        'rev_fy2': _g('Rev_FY2'),
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
                    # Full industry groups for medians
                    _full_ind_grouped = full_group.groupby('Industry') if 'Industry' in full_group.columns else None

                    for ind_name, ind_group in group.groupby('Industry'):
                        if not ind_name or pd.isna(ind_name):
                            continue
                        ind_stocks = [make_stock(row) for _, row in ind_group.iterrows()]
                        ind_stocks.sort(key=lambda x: x.get('rs_rank') or 0, reverse=True)

                        # Full industry for medians (all stocks regardless of filter)
                        full_ind = _full_ind_grouped.get_group(ind_name) if _full_ind_grouped and ind_name in _full_ind_grouped.groups else ind_group

                        def _ind_median(col_name, pos_only=False):
                            vals = pd.to_numeric(full_ind.get(col_name, pd.Series()), errors='coerce').dropna()
                            if pos_only: vals = vals[vals > 0]
                            return float(vals.median()) if len(vals) > 0 else None

                        def _ind_mean(col_name):
                            vals = pd.to_numeric(full_ind.get(col_name, pd.Series()), errors='coerce').dropna()
                            return float(vals.mean()) if len(vals) > 0 else None

                        _ind_pe = _ind_median('PE', pos_only=True)
                        _sec_pe = stats['median_pe']
                        _ind_pe_vs_sec = round(_ind_pe / _sec_pe, 2) if _ind_pe and _sec_pe and _sec_pe > 0 else None

                        industries.append({
                            'industry': ind_name,
                            'count': len(ind_group),
                            'median_pe': _ind_pe,
                            'pe_vs_sector': _ind_pe_vs_sec,
                            'median_fwd_pe': _ind_median('FwdPE', pos_only=True),
                            'median_eps': _ind_median('EPS_Act'),
                            'median_eps_ttm': _ind_median('EPS_TTM'),
                            'median_eps_ntm': _ind_median('EPS_NTM'),
                            'median_fy1': _ind_median('EPS_FY1'),
                            'median_fy2': _ind_median('EPS_FY2'),
                            'median_rev_ttm': _ind_median('Rev_TTM'),
                            'median_rev_ntm': _ind_median('Rev_NTM'),
                            'median_op_margin': _ind_median('OpMargin'),
                            'median_net_margin': _ind_median('NetMargin'),
                            'median_roic': _ind_median('ROIC'),
                            'median_fcf': _ind_median('FCF'),
                            'median_nd_ebitda': _ind_median('ND_EBITDA'),
                            'median_ev_ebitda': _ind_median('EV_EBITDA', pos_only=True),
                            'median_rs': _ind_median('RS_Rank'),
                            'median_rs_chg1w': _ind_mean('RS_Chg1W'),
                            'median_rs_chg1m': _ind_mean('RS_Chg1M'),
                            'median_rs_chg3m': _ind_mean('RS_Chg3M'),
                            'median_target': _ind_median('Target'),
                            'stocks': ind_stocks,
                        })
                    industries.sort(key=lambda x: x['count'], reverse=True)
                stats['industries'] = industries

                sector_stats.append(stats)

            sector_stats.sort(key=lambda x: x['pct_of_sector'], reverse=True)

    _as_of_used = _as_of_label

    return render_template('screener.html',
                           active_section='screener',
                           data=data,
                           filters=filters,
                           sectors=sectors,
                           stage_dist=stage_dist,
                           market_regime=market_regime,
                           universe_total=universe_total,
                           sector_stats=sector_stats,
                           fetch_time=fetch_time,
                           as_of_date=_as_of_used)


@app.route('/api/rolling_12m/<symbol>')
def rolling_12m_api(symbol):
    """Return rolling 12-month EPS and Revenue with estimate bounds."""
    try:
        return _rolling_12m_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _rolling_12m_impl(symbol):
    import pickle
    from pathlib import Path

    pkl_path = Path(__file__).parent.parent.parent / 'data' / 'mktt' / 'refinitiv_fundamentals.pkl'
    if not pkl_path.exists():
        return jsonify({'error': 'No data'}), 404
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)

    quarterly = data.get('quarterly')
    if quarterly is None:
        return jsonify({'error': 'No quarterly data'}), 404

    q = quarterly[quarterly['Symbol'] == symbol].copy()
    if q.empty:
        return jsonify({'error': f'No data for {symbol}'}), 404

    q['Date'] = pd.to_datetime(q['Date'], errors='coerce')
    q = q.sort_values('Date').dropna(subset=['Date'])

    def _n(v):
        if v is None or v == '' or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except:
            return None

    q['eps'] = q['Earnings Per Share - Actual'].map(_n)
    q['eps_est'] = q['Earnings Per Share - Mean Estimate'].map(_n)
    q['rev'] = q['Revenue - Actual'].map(_n)

    # Rolling 12M (4 quarter sum) for actuals
    dates = []
    eps_ttm = []
    rev_ttm = []
    eps_est_ttm = []

    for i in range(3, len(q)):
        window = q.iloc[i-3:i+1]
        dt = q.iloc[i]['Date']

        eps_vals = [window.iloc[j]['eps'] for j in range(4)]
        rev_vals = [window.iloc[j]['rev'] for j in range(4)]
        est_vals = [window.iloc[j]['eps_est'] for j in range(4)]

        if all(v is not None for v in eps_vals):
            eps_ttm.append(round(sum(eps_vals), 2))
        else:
            eps_ttm.append(None)

        if all(v is not None for v in rev_vals):
            rev_ttm.append(round(sum(rev_vals) / 1e6, 1))
        else:
            rev_ttm.append(None)

        if all(v is not None for v in est_vals):
            eps_est_ttm.append(round(sum(est_vals), 2))
        else:
            eps_est_ttm.append(None)

        dates.append(str(dt)[:10])

    # Forward: add NTM from forward quarterly estimates
    fwd_q = data.get('forward_quarterly')
    fwd_dates = []
    fwd_eps_mean = []
    fwd_eps_high = []
    fwd_eps_low = []
    fwd_rev_mean = []
    fwd_rev_high = []
    fwd_rev_low = []

    if fwd_q is not None:
        fq = fwd_q[fwd_q['Symbol'] == symbol]
        if len(fq) >= 4:
            eps_fwd_mean = pd.to_numeric(fq.get('Earnings Per Share - Mean', pd.Series()), errors='coerce').values
            eps_fwd_high = pd.to_numeric(fq.get('Earnings Per Share - High', pd.Series()), errors='coerce').values
            eps_fwd_low = pd.to_numeric(fq.get('Earnings Per Share - Low', pd.Series()), errors='coerce').values
            rev_fwd_mean_v = pd.to_numeric(fq.get('Revenue - Mean', pd.Series()), errors='coerce').values
            rev_fwd_high_v = pd.to_numeric(fq.get('Revenue - High', pd.Series()), errors='coerce').values
            rev_fwd_low_v = pd.to_numeric(fq.get('Revenue - Low', pd.Series()), errors='coerce').values

            last_actuals_eps = [q.iloc[-(4-j)]['eps'] for j in range(4) if len(q) > (4-j-1)]
            last_actuals_rev = [q.iloc[-(4-j)]['rev'] for j in range(4) if len(q) > (4-j-1)]

            def _blend(actuals, fwd_vals, step, div=1):
                actual_part = actuals[step:] if step < len(actuals) else []
                fwd_part = fwd_vals[:step].tolist()
                a = [v for v in actual_part if v is not None]
                f = [v for v in fwd_part if not pd.isna(v)]
                if len(a) + len(f) == 4:
                    return round((sum(a) + sum(f)) / div, 2 if div == 1 else 1)
                return None

            for step in range(1, 5):
                if step > len(eps_fwd_mean):
                    break
                fwd_eps_mean.append(_blend(last_actuals_eps, eps_fwd_mean, step))
                fwd_eps_high.append(_blend(last_actuals_eps, eps_fwd_high, step))
                fwd_eps_low.append(_blend(last_actuals_eps, eps_fwd_low, step))
                fwd_rev_mean.append(_blend(last_actuals_rev, rev_fwd_mean_v, step, 1e6))
                fwd_rev_high.append(_blend(last_actuals_rev, rev_fwd_high_v, step, 1e6))
                fwd_rev_low.append(_blend(last_actuals_rev, rev_fwd_low_v, step, 1e6))

                last_dt = pd.to_datetime(dates[-1]) if dates else q['Date'].iloc[-1]
                fwd_dates.append(str(last_dt + pd.DateOffset(months=3 * step))[:10])

    # Sanitize: replace NaN/inf with None for JSON
    import math
    def _clean(lst):
        return [v if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else None for v in lst]

    result = {
        'dates': dates,
        'eps_ttm': _clean(eps_ttm),
        'eps_est_ttm': _clean(eps_est_ttm),
        'rev_ttm': _clean(rev_ttm),
        'fwd_dates': fwd_dates,
        'fwd_eps_mean': _clean(fwd_eps_mean),
        'fwd_eps_high': _clean(fwd_eps_high),
        'fwd_eps_low': _clean(fwd_eps_low),
        'fwd_rev_mean': _clean(fwd_rev_mean),
        'fwd_rev_high': _clean(fwd_rev_high),
        'fwd_rev_low': _clean(fwd_rev_low),
    }
    return jsonify(result)


@app.route('/watchlist')
def watchlist_page():
    """Watchlist page — stocks stored client-side, data fetched server-side."""
    return render_template('watchlist.html', active_section='watchlist')


@app.route('/api/watchlist')
def watchlist_api():
    """Return enriched data for a list of symbols (passed as ?sym=X&sym=Y)."""
    try:
        return _watchlist_api_impl()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _watchlist_api_impl():
    from data_manager import load_prices, load_universe
    symbols = request.args.getlist('sym')
    if not symbols:
        return jsonify({'stocks': []})

    close = load_prices('close')
    uni = load_universe()
    rfv = load_refinitiv_snapshot()

    # Find last dense row
    min_stocks = len(close.columns) * 0.5
    _idx = len(close) - 1
    for _i in range(len(close) - 1, max(len(close) - 10, 0), -1):
        if close.iloc[_i].notna().sum() >= min_stocks:
            _idx = _i
            break
    _close_slice = close.iloc[:_idx + 1]
    last_prices = _close_slice.iloc[-1]
    prev_prices = _close_slice.iloc[-2] if _idx > 0 else last_prices

    # RS
    rs_ranks = {}
    if len(_close_slice) > 126:
        ret_6m = (_close_slice.iloc[-1] / _close_slice.iloc[-126] - 1)
        rs_ranks = (ret_6m.rank(pct=True) * 100).to_dict()

    # Historical prices for returns
    _p1w = _close_slice.iloc[-6] if len(_close_slice) > 6 else last_prices
    _p1m = _close_slice.iloc[-22] if len(_close_slice) > 22 else last_prices
    _p3m = _close_slice.iloc[-64] if len(_close_slice) > 64 else last_prices

    stocks = []
    for sym in symbols:
        price = last_prices.get(sym)
        if pd.isna(price) or price is None:
            stocks.append({'symbol': sym, 'error': 'No price data'})
            continue
        prev = prev_prices.get(sym)
        r = rfv.get(sym, {})
        eps = r.get('eps_act')
        pe = float(price) / float(eps) if eps and eps > 0 else None
        fy1 = r.get('fy1_eps')
        fwd_pe = float(price) / float(fy1) if fy1 and fy1 > 0 else None
        stocks.append({
            'symbol': sym,
            'price': round(float(price), 2),
            'change': round(((price / prev) - 1) * 100, 2) if pd.notna(prev) and prev > 0 else 0,
            'sector': r.get('sector', ''),
            'industry': r.get('industry', ''),
            'pe': round(pe, 1) if pe else None,
            'fwd_pe': round(fwd_pe, 1) if fwd_pe else None,
            'eps_act': r.get('eps_act'),
            'eps_fy1': r.get('fy1_eps'),
            'eps_fy2': r.get('fy2_eps'),
            'op_margin': r.get('op_margin'),
            'roic': r.get('roic'),
            'rs': round(rs_ranks.get(sym, 0)) if sym in rs_ranks else None,
            'target': r.get('target'),
            'ret_1w': round(((price / _p1w.get(sym)) - 1) * 100, 1) if pd.notna(_p1w.get(sym)) and _p1w.get(sym) > 0 else None,
            'ret_1m': round(((price / _p1m.get(sym)) - 1) * 100, 1) if pd.notna(_p1m.get(sym)) and _p1m.get(sym) > 0 else None,
            'ret_3m': round(((price / _p3m.get(sym)) - 1) * 100, 1) if pd.notna(_p3m.get(sym)) and _p3m.get(sym) > 0 else None,
        })

    # Total stocks per sector/industry in full universe (for % calculation)
    sector_counts = {}
    industry_counts = {}
    for sym, rec in rfv.items():
        s = rec.get('sector')
        ind = rec.get('industry')
        if s:
            sector_counts[s] = sector_counts.get(s, 0) + 1
        if ind:
            industry_counts[ind] = industry_counts.get(ind, 0) + 1

    return jsonify({
        'stocks': stocks,
        'as_of': str(_close_slice.index[_idx])[:10],
        'sector_counts': sector_counts,
        'industry_counts': industry_counts,
        'universe_total': len([r for r in rfv.values() if r.get('sector')]),
    })


@app.route('/api/sector_map')
def sector_map_api():
    """Return sector/industry breakdown by a given criteria dimension."""
    try:
        return _sector_map_impl()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _sector_map_impl():
    from data_manager import load_prices, load_universe
    import numpy as np

    dimension = request.args.get('dim', 'pca_regime')  # what to color/group by
    min_turnover = int(float(request.args.get('min_turnover', '500000')))

    close = load_prices('close')
    uni = load_universe()
    rfv = load_refinitiv_snapshot()
    cls = load_classification_lookups()

    if close is None or close.empty:
        return jsonify({'error': 'No price data'}), 404

    # Find last dense row
    min_stocks = len(close.columns) * 0.5
    _idx = len(close) - 1
    for _i in range(len(close) - 1, max(len(close) - 10, 0), -1):
        if close.iloc[_i].notna().sum() >= min_stocks:
            _idx = _i
            break
    _close_slice = close.iloc[:_idx + 1]
    last_prices = _close_slice.iloc[-1]

    # RS ranks
    rs_ranks = {}
    rs_chg1m = {}
    if len(_close_slice) > 147:
        ret_6m = (_close_slice.iloc[-1] / _close_slice.iloc[-126] - 1)
        rs_pct = ret_6m.rank(pct=True) * 100
        rs_ranks = rs_pct.to_dict()
        s = _close_slice.iloc[:-21]
        r6_old = (s.iloc[-1] / s.iloc[-126] - 1)
        rs_old = (r6_old.rank(pct=True) * 100).to_dict()
        rs_chg1m = {sym: rs_ranks.get(sym, 0) - rs_old.get(sym, 0) for sym in rs_ranks}

    rows = []
    for sym in close.columns:
        price = last_prices.get(sym)
        if pd.isna(price) or price <= 0:
            continue
        uni_row = uni[uni['symbol'] == sym].iloc[0] if uni is not None and sym in uni['symbol'].values else None
        turnover = float(uni_row['turnover']) if uni_row is not None and pd.notna(uni_row.get('turnover')) else 0
        if turnover < min_turnover:
            continue

        r = rfv.get(sym, {})
        sector = r.get('sector')
        if not sector:
            continue
        industry = r.get('industry') or 'Unknown'
        eps_act = r.get('eps_act')
        fy1_eps = r.get('fy1_eps')

        # Compute PE
        pe = float(price) / float(eps_act) if eps_act and eps_act > 0 else None

        # Classification values
        pca = cls.get('pca20', {}).get(sym, 'Unknown')
        stage = cls.get('stages', {}).get(sym, 'Unknown')
        eps_acc_info = cls.get('eps_accel', {}).get(sym, {})
        eps_mom = eps_acc_info.get('label', 'Unknown') if isinstance(eps_acc_info, dict) else 'Unknown'

        # EPS growth direction
        eps_growth_dir = 'Unknown'
        if eps_act and fy1_eps:
            eps_growth_dir = 'Growing' if fy1_eps > eps_act else 'Declining' if fy1_eps < eps_act else 'Flat'

        # RS bucket
        rs_val = rs_ranks.get(sym)
        rs_bucket = 'Unknown'
        if rs_val is not None:
            if rs_val >= 80: rs_bucket = 'RS 80+'
            elif rs_val >= 60: rs_bucket = 'RS 60-80'
            elif rs_val >= 40: rs_bucket = 'RS 40-60'
            elif rs_val >= 20: rs_bucket = 'RS 20-40'
            else: rs_bucket = 'RS 0-20'

        # RS momentum bucket
        chg1m = rs_chg1m.get(sym, 0)
        rs_mom = 'Unknown'
        if chg1m > 5: rs_mom = 'Improving'
        elif chg1m > -5: rs_mom = 'Stable'
        else: rs_mom = 'Deteriorating'

        # PE vs sector bucket (need sector median)
        pe_bucket = 'Unknown'  # filled below

        rows.append({
            'symbol': sym, 'sector': sector, 'industry': industry,
            'pe': pe, 'turnover': turnover,
            'pca_regime': pca, 'stage': stage, 'eps_momentum': eps_mom,
            'eps_growth': eps_growth_dir, 'rs_bucket': rs_bucket,
            'rs_momentum': rs_mom,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return jsonify({'error': 'No data'}), 404

    # PE vs sector bucket
    if 'pe' in df.columns:
        sector_med_pe = df[df['pe'].notna() & (df['pe'] > 0)].groupby('sector')['pe'].median()
        def _pe_bucket(row):
            if pd.isna(row.get('pe')) or row['pe'] is None:
                return 'No PE'
            med = sector_med_pe.get(row['sector'])
            if med is None or med <= 0:
                return 'No PE'
            ratio = row['pe'] / med
            if ratio < 0.7: return 'Deep Discount'
            elif ratio < 0.9: return 'Discount'
            elif ratio < 1.1: return 'Fair'
            elif ratio < 1.3: return 'Premium'
            else: return 'High Premium'
        df['pe_vs_sector'] = df.apply(_pe_bucket, axis=1)

    # Available dimensions
    dim_map = {
        'pca_regime': 'pca_regime', 'stage': 'stage', 'eps_momentum': 'eps_momentum',
        'eps_growth': 'eps_growth', 'rs_bucket': 'rs_bucket', 'rs_momentum': 'rs_momentum',
        'pe_vs_sector': 'pe_vs_sector',
    }
    col = dim_map.get(dimension, 'pca_regime')

    # Build treemap data: sector -> industry -> count, colored by dimension
    treemap_data = []
    for sector, sec_group in df.groupby('sector'):
        for industry, ind_group in sec_group.groupby('industry'):
            for dim_val, dim_group in ind_group.groupby(col):
                treemap_data.append({
                    'sector': sector,
                    'industry': industry,
                    'dimension': str(dim_val),
                    'count': len(dim_group),
                    'symbols': dim_group['symbol'].tolist(),
                })

    # Summary: sector × dimension counts
    summary = df.groupby(['sector', col]).size().reset_index(name='count')
    summary.columns = ['sector', 'dimension', 'count']
    summary_list = summary.to_dict('records')

    # Overall dimension distribution
    overall = df[col].value_counts().to_dict()

    return jsonify({
        'dimension': dimension,
        'dimensions_available': list(dim_map.keys()),
        'treemap': treemap_data,
        'summary': summary_list,
        'overall': {str(k): int(v) for k, v in overall.items()},
        'total_stocks': len(df),
    })


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
    try:
        return _chart_api_impl(symbol)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/freshness')
def freshness_api():
    """Return data freshness report as JSON."""
    try:
        from data_freshness import full_report
        return jsonify(full_report())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _chart_api_impl(symbol):
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


@app.route('/api/fundamentals/<symbol>')
def fundamentals_api(symbol):
    """Return quarterly fundamentals (margins, EPS, FCF) for a symbol."""
    try:
        return _fundamentals_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _fundamentals_impl(symbol):
    import pickle
    from pathlib import Path
    pkl_path = Path(__file__).parent.parent.parent / 'data' / 'mktt' / 'refinitiv_fundamentals.pkl'
    if not pkl_path.exists():
        return jsonify({'error': 'No data'}), 404
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    quarterly = data.get('quarterly')
    if quarterly is None:
        return jsonify({'error': 'No quarterly data'}), 404
    q = quarterly[quarterly['Symbol'] == symbol].copy()
    if q.empty:
        return jsonify({'error': f'No data for {symbol}'}), 404
    q['Date'] = pd.to_datetime(q['Date'])
    q = q.sort_values('Date')

    def _n(v):
        """Convert value to float, returning None for empty/invalid."""
        if v is None or v == '' or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _s(col):
        return [round(x, 2) if x is not None else None for x in [_n(v) for v in q[col]]]

    def _sm(col, div=1):
        return [round(x/div, 1) if x is not None else None for x in [_n(v) for v in q[col]]]

    return jsonify({
        'dates': [str(d)[:10] for d in q['Date']],
        'eps': _s('Earnings Per Share - Actual'),
        'eps_est': _s('Earnings Per Share - Mean Estimate'),
        'revenue': _sm('Revenue - Actual', 1e6),
        'rev_est': _sm('Revenue - Mean Estimate', 1e6),
        'op_margin': _s('Operating Margin, Percent'),
        'net_margin': _s('Net Profit Margin, (%)'),
        'fcf': _sm('Free Cash Flow', 1e6),
    })


@app.route('/api/eps_ttm_forward/<symbol>')
def eps_ttm_forward_api(symbol):
    """Return forward TTM EPS curve at current, -10d, -30d, -60d snapshots."""
    try:
        return _eps_ttm_forward_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _eps_ttm_forward_impl(symbol):
    import pickle
    from pathlib import Path
    from datetime import timedelta
    import numpy as np

    pkl_path = Path(__file__).parent.parent.parent / 'data' / 'mktt' / 'refinitiv_fundamentals.pkl'
    if not pkl_path.exists():
        return jsonify({'error': 'No data'}), 404
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)

    quarterly = data.get('quarterly')
    trend_fy1 = data.get('trend_eps_fy1')
    trend_fy2 = data.get('trend_eps_fy2')
    if quarterly is None or trend_fy1 is None or trend_fy2 is None:
        return jsonify({'error': 'Missing data'}), 404

    # Get quarterly actuals
    q = quarterly[quarterly['Symbol'] == symbol].copy()
    if q.empty:
        return jsonify({'error': f'No quarterly data for {symbol}'}), 404
    q['Date'] = pd.to_datetime(q['Date'])
    q = q.sort_values('Date')
    q['EPS'] = pd.to_numeric(q['Earnings Per Share - Actual'], errors='coerce')
    q = q.dropna(subset=['EPS'])
    if len(q) < 4:
        return jsonify({'error': f'Not enough quarterly EPS data for {symbol}'}), 404

    # Get FY1/FY2 trend data
    fy1 = trend_fy1[trend_fy1['Symbol'] == symbol].copy()
    fy2 = trend_fy2[trend_fy2['Symbol'] == symbol].copy()
    if fy1.empty or fy2.empty:
        return jsonify({'error': f'No estimate trend data for {symbol}'}), 404
    fy1['Date'] = pd.to_datetime(fy1['Date'])
    fy2['Date'] = pd.to_datetime(fy2['Date'])
    fy1['Mean'] = pd.to_numeric(fy1['Earnings Per Share - Mean'], errors='coerce')
    fy2['Mean'] = pd.to_numeric(fy2['Earnings Per Share - Mean'], errors='coerce')
    fy1 = fy1.sort_values('Date')
    fy2 = fy2.sort_values('Date')

    # Compute seasonal weights from last 8 quarterly actuals
    last_q = q.tail(8)
    if len(last_q) >= 4:
        annual_sum = last_q['EPS'].tail(4).sum()
        if annual_sum != 0:
            weights = (last_q['EPS'].tail(4).values / annual_sum).tolist()
        else:
            weights = [0.25, 0.25, 0.25, 0.25]
    else:
        weights = [0.25, 0.25, 0.25, 0.25]

    # Determine quarter dates for next 8 quarters from last actual
    last_actual_date = q['Date'].iloc[-1]
    quarter_dates = []
    d = last_actual_date
    for i in range(8):
        d = d + pd.DateOffset(months=3)
        quarter_dates.append(d)

    # Function to get estimate at a given snapshot date
    def get_estimates_at(snapshot_date):
        """Get FY1 and FY2 estimate closest to (but not after) snapshot_date."""
        f1 = fy1[fy1['Date'] <= snapshot_date]
        f2 = fy2[fy2['Date'] <= snapshot_date]
        fy1_val = float(f1['Mean'].iloc[-1]) if not f1.empty else None
        fy2_val = float(f2['Mean'].iloc[-1]) if not f2.empty else None
        return fy1_val, fy2_val

    # Build forward TTM EPS for a snapshot
    def build_ttm_curve(snapshot_date):
        fy1_val, fy2_val = get_estimates_at(snapshot_date)
        if fy1_val is None or fy2_val is None:
            return None

        # Distribute annual estimates into quarterly using seasonal weights
        fy1_quarters = [fy1_val * w for w in weights]
        fy2_quarters = [fy2_val * w for w in weights]

        # Build 8 forward quarters: first 4 from FY1, next 4 from FY2
        forward_q = fy1_quarters + fy2_quarters

        # Actual trailing quarters (last 4)
        trailing = q['EPS'].tail(4).tolist()

        # TTM at each future quarter = sum of appropriate 4-quarter window
        # Window slides: at Q+1, TTM = trailing[1:4] + forward[0]
        # at Q+2, TTM = trailing[2:4] + forward[0:2], etc.
        all_eps = trailing + forward_q  # indices 0-3 = trailing, 4-11 = forward
        ttm_values = []
        for i in range(8):
            window = all_eps[i+1: i+5]  # 4 quarters ending at forward quarter i+1
            ttm_values.append(round(sum(window), 2))

        return ttm_values

    # Build curves based on actual revision dates (not fixed day offsets)
    # Collect all unique dates where FY1 or FY2 estimate was updated
    all_dates = sorted(set(
        fy1[fy1['Mean'].notna()]['Date'].tolist() +
        fy2[fy2['Mean'].notna()]['Date'].tolist()
    ), reverse=True)  # most recent first

    # Number of revisions to show (default 3, configurable via query param)
    from flask import request as _req
    n_revisions = int(_req.args.get('n', 3))
    n_revisions = max(1, min(n_revisions, len(all_dates)))

    # Take the last n unique revision dates
    snapshot_dates = all_dates[:n_revisions]

    result = {
        'quarter_labels': [f"{d.year}-Q{(d.month - 1)//3 + 1}" for d in quarter_dates],
        'quarter_dates': [d.strftime('%Y-%m-%d') for d in quarter_dates],
        'curves': {},
    }

    curves_list = []
    for i, snap_date in enumerate(snapshot_dates):
        curve = build_ttm_curve(snap_date)
        if curve:
            label = 'Current (' + snap_date.strftime('%m/%d') + ')' if i == 0 else snap_date.strftime('%Y-%m-%d')
            curves_list.append({'label': label, 'values': curve})

    result['curves'] = curves_list

    # Also add current TTM (actual trailing 4Q)
    if len(q) >= 4:
        result['current_ttm'] = round(float(q['EPS'].tail(4).sum()), 2)

    result['n_available'] = len(all_dates)
    return jsonify(result)


@app.route('/api/revisions/<symbol>')
def revisions_api(symbol):
    """Return EPS/Revenue estimate revision trends for a symbol."""
    try:
        return _revisions_impl(symbol)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _revisions_impl(symbol):
    import pickle
    from pathlib import Path
    pkl_path = Path(__file__).parent.parent.parent / 'data' / 'mktt' / 'refinitiv_fundamentals.pkl'
    if not pkl_path.exists():
        return jsonify({'error': 'No data'}), 404
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)

    result = {}
    for key, label in [('trend_eps_fy1', 'eps_fy1'), ('trend_eps_fy2', 'eps_fy2'),
                        ('trend_rev_fy1', 'rev_fy1'), ('trend_rev_fy2', 'rev_fy2')]:
        df = data.get(key)
        if df is None:
            continue
        t = df[df['Symbol'] == symbol].copy()
        if t.empty:
            continue
        t['Date'] = pd.to_datetime(t['Date'])
        t = t.sort_values('Date')
        def _safe(v, div=1):
            if v is None or v == '' or (isinstance(v, float) and pd.isna(v)):
                return None
            try:
                return round(float(v) / div, 3)
            except (ValueError, TypeError):
                return None

        if 'Earnings Per Share - Mean' in t.columns:
            result[label] = {
                'dates': [str(d)[:10] for d in t['Date']],
                'mean': [_safe(v) for v in t['Earnings Per Share - Mean']],
                'high': [_safe(v) for v in t.get('Earnings Per Share - High', [])],
                'low': [_safe(v) for v in t.get('Earnings Per Share - Low', [])],
            }
        elif 'Revenue - Mean' in t.columns:
            result[label] = {
                'dates': [str(d)[:10] for d in t['Date']],
                'mean': [_safe(v, 1e6) for v in t['Revenue - Mean']],
            }

    if not result:
        return jsonify({'error': f'No revision data for {symbol}'}), 404
    return jsonify(result)


if __name__ == '__main__':
    # Auto-update prices if stale (>16 hours old)
    from data_manager import auto_update_if_stale
    try:
        auto_update_if_stale(max_age_hours=16)
    except Exception as e:
        print(f"  Auto-update skipped: {e}")

    app.run(debug=True, port=5001, use_reloader=True, reloader_type='stat')
