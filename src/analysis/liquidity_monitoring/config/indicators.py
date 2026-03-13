"""
Liquidity Indicators Configuration
Based on Michael Howell's 3-layer Global Liquidity Index framework

Scoring convention:
    +1 = Bullish for liquidity
     0 = Neutral
    -1 = Bearish for liquidity

Layer 2b (Economic Reality) uses COUNTERINTUITIVE scoring:
    Weak economy = CB will ease = bullish liquidity signal = +1
"""

# =============================================================================
# LAYER 1: CENTRAL BANK LIQUIDITY
# =============================================================================
# Exogenous impulse from Federal Reserve policy
# Score range: -4 to +4

LAYER1_INDICATORS = {
    'fed_balance_sheet': {
        'fred_code': 'WALCL',
        'name': 'Fed Balance Sheet',
        'description': 'Total Assets of Federal Reserve',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',  # 12-month rate of change
        'bullish_threshold': 0,     # ROC > 0 = expanding = bullish
        'bearish_threshold': 0,     # ROC < 0 = contracting = bearish
        'invert': False,
    },
    'tga': {
        'fred_code': 'WTREGEN',
        'name': 'Treasury General Account',
        'description': 'Treasury cash balance at Fed - drains reserves when rising',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': True,  # Rising TGA = drain on reserves = bearish
    },
    'rrp': {
        'fred_code': 'RRPONTSYD',
        'name': 'Reverse Repo Facility',
        'description': 'ON RRP usage - liquidity drain when high',
        'frequency': 'daily',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': True,  # Rising RRP = drain = bearish
    },
    'fed_funds': {
        'fred_code': 'DFF',
        'name': 'Fed Funds Rate',
        'description': 'Effective Federal Funds Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',  # Used for real rate calculation
        'derived': False,
    },
    'cpi': {
        'fred_code': 'CPIAUCSL',
        'name': 'CPI All Items',
        'description': 'Consumer Price Index for real rate calculation',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'component',  # Used for real rate and L2b momentum
        'derived': False,
    },
    'dgs10': {
        'fred_code': 'DGS10',
        'name': '10-Year Treasury',
        'description': '10-Year Treasury Constant Maturity Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',  # Used for yield curve
        'derived': False,
    },
    'dgs2': {
        'fred_code': 'DGS2',
        'name': '2-Year Treasury',
        'description': '2-Year Treasury Constant Maturity Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',  # Used for yield curve
        'derived': False,
    },
    # Derived indicators (calculated, not fetched)
    'net_liquidity': {
        'fred_code': None,
        'name': 'Fed Net Liquidity',
        'description': 'WALCL - TGA - RRP (actual liquidity in system)',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
        'derived': True,
        'formula': 'WALCL - WTREGEN - RRPONTSYD',
    },
    'real_policy_rate': {
        'fred_code': None,
        'name': 'Real Policy Rate',
        'description': 'Fed Funds - CPI YoY (real interest rate)',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 0,      # Negative real rate = bullish
        'neutral_high': 1.0,         # 0-1% = neutral
        'bearish_threshold': 1.0,    # >1% = bearish
        'invert': True,              # Lower is better
        'derived': True,
        'formula': 'DFF - CPI_YOY',
    },
    'yield_curve': {
        'fred_code': None,
        'name': 'Yield Curve (10Y-2Y)',
        'description': 'Treasury yield curve slope',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 1.5,    # >150bp steep = bullish
        'neutral_low': 0,            # 0-150bp = neutral
        'bearish_threshold': 0,      # Inverted (<0) = bearish
        'invert': False,
        'derived': True,
        'formula': 'DGS10 - DGS2',
    },
}

# =============================================================================
# LAYER 2a: PRIVATE SECTOR / WHOLESALE LIQUIDITY
# =============================================================================
# Amplitude and transmission of CB policy through private system
# Score range: -6 to +6

LAYER2A_INDICATORS = {
    'bank_credit': {
        'fred_code': 'TOTLL',
        'name': 'Bank Credit Total',
        'description': 'Total Loans and Leases at Commercial Banks (H.8)',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
    },
    'ci_loans': {
        'fred_code': 'BUSLOANS',
        'name': 'C&I Loans',
        'description': 'Commercial and Industrial Loans',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
    },
    'm2': {
        'fred_code': 'M2SL',
        'name': 'M2 Money Supply',
        'description': 'M2 Money Stock',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
    },
    'dxy': {
        'fred_code': 'DTWEXBGS',
        'name': 'Dollar Index (Broad)',
        'description': 'Trade Weighted U.S. Dollar Index: Broad',
        'frequency': 'daily',
        'units': 'index',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': True,  # Weaker dollar = more global liquidity = bullish
    },
    'hy_spread': {
        'fred_code': 'BAMLH0A0HYM2',
        'name': 'HY Credit Spread',
        'description': 'ICE BofA US High Yield OAS',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 4.0,    # <400bp = bullish
        'bearish_threshold': 6.0,    # >600bp = bearish
        'invert': True,              # Tighter spreads = bullish
    },
    'ig_spread': {
        'fred_code': 'BAMLC0A0CM',
        'name': 'IG Credit Spread',
        'description': 'ICE BofA US Corporate OAS',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 1.0,    # <100bp = bullish
        'bearish_threshold': 2.0,    # >200bp = bearish
        'invert': True,
    },
    'vix': {
        'fred_code': 'VIXCLS',
        'name': 'VIX',
        'description': 'CBOE Volatility Index - proxy for collateral haircuts',
        'frequency': 'daily',
        'units': 'index',
        'signal_type': 'level',
        'bullish_threshold': 15,     # <15 = low vol = bullish
        'bearish_threshold': 25,     # >25 = high vol = bearish
        'invert': True,
    },
    'nfci': {
        'fred_code': 'NFCI',
        'name': 'Chicago Fed NFCI',
        'description': 'National Financial Conditions Index (negative = loose)',
        'frequency': 'weekly',
        'units': 'index',
        'signal_type': 'level',
        'bullish_threshold': 0,      # Negative = loose = bullish
        'bearish_threshold': 0,      # Positive = tight = bearish
        'invert': True,              # More negative = more bullish
    },
    'sofr': {
        'fred_code': 'SOFR',
        'name': 'SOFR',
        'description': 'Secured Overnight Financing Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',  # Used for SOFR-EFFR spread
        'derived': False,
    },
    'effr': {
        'fred_code': 'EFFR',
        'name': 'EFFR',
        'description': 'Effective Federal Funds Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',  # Used for SOFR-EFFR spread
        'derived': False,
    },
    'mmf_assets': {
        'fred_code': 'WRMFSL',
        'name': 'MMF Total Assets',
        'description': 'Money Market Funds Total Assets',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,  # Growing MMF = more cash looking for yield
    },
    # Derived
    'sofr_effr_spread': {
        'fred_code': None,
        'name': 'SOFR-EFFR Spread',
        'description': 'Repo stress indicator',
        'frequency': 'daily',
        'units': 'basis_points',
        'signal_type': 'level',
        'bullish_threshold': 5,      # <5bp = normal = bullish
        'bearish_threshold': 15,     # >15bp = stress = bearish
        'invert': True,
        'derived': True,
        'formula': '(SOFR - EFFR) * 100',
    },
}

# =============================================================================
# LAYER 2b: ECONOMIC REALITY GAUGES
# =============================================================================
# COUNTERINTUITIVE SCORING:
# Weak economy = CB will ease = bullish liquidity signal = +1
# Strong/overheating economy = CB will tighten = bearish = -1
# Score range: -7 to +7

LAYER2B_INDICATORS = {
    'capacity_util': {
        'fred_code': 'TCU',
        'name': 'Capacity Utilization',
        'description': 'Total Industry Capacity Utilization',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 78,     # <78% = slack = CB eases = bullish
        'neutral_high': 81.5,        # 78-81.5% = neutral
        'bearish_threshold': 81.5,   # >81.5% = overheating = CB tightens = bearish
        'invert': True,              # COUNTERINTUITIVE: lower = bullish
        'counterintuitive': True,
    },
    'industrial_prod': {
        'fred_code': 'INDPRO',
        'name': 'Industrial Production',
        'description': 'Industrial Production Index',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'roc_12m',
        'bullish_threshold': 5,      # <5% growth = weak = CB eases = bullish
        'bearish_threshold': 7,      # >7% = strong = CB tightens = bearish
        'invert': True,              # COUNTERINTUITIVE
        'counterintuitive': True,
    },
    'unemployment': {
        'fred_code': 'UNRATE',
        'name': 'Unemployment Rate',
        'description': 'Civilian Unemployment Rate',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'roc_29m',    # 29-month rate of change per Howell spec
        'bullish_threshold': 0,      # Rising unemployment = CB eases = bullish
        'bearish_threshold': 0,      # Falling rapidly = CB tightens = bearish
        'invert': False,             # Rising = bullish (counterintuitive but not inverted)
        'counterintuitive': True,
    },
    'cpi_level': {
        'fred_code': 'CPIAUCSL',     # Same as L1, reused
        'name': 'CPI Level',
        'description': 'CPI YoY for inflation assessment',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'yoy',
        'bullish_threshold': 3.2,    # <3.2% = low inflation = CB can ease = bullish
        'neutral_high': 5.0,         # 3.2-5% = neutral
        'bearish_threshold': 5.0,    # >5% = high inflation = CB tightens = bearish
        'invert': True,              # Lower inflation = bullish
        'counterintuitive': True,
    },
    'cpi_momentum': {
        'fred_code': 'CPIAUCSL',     # Same series, different calculation
        'name': 'CPI Momentum',
        'description': '3-month annualized vs 12-month (deceleration signal)',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'momentum',   # 3m ann. vs 12m
        'bullish_threshold': 0,      # 3m < 12m = deceleration = CB can ease = bullish
        'bearish_threshold': 0,      # 3m > 12m = acceleration = CB tightens = bearish
        'invert': False,             # Negative momentum (decel) = bullish
        'counterintuitive': True,
        'derived': True,
        'formula': 'CPI_3M_ANN - CPI_12M',
    },
    'ppi_commodities': {
        'fred_code': 'PPIACO',
        'name': 'PPI All Commodities',
        'description': 'Producer Price Index - All Commodities (sensitive materials proxy)',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'level',
        'bullish_threshold': 50,     # <50 = prices falling = CB can ease = bullish
        'bearish_threshold': 60,     # >60 = prices rising fast = CB tightens = bearish
        'invert': True,              # COUNTERINTUITIVE
        'counterintuitive': True,
    },
}

# =============================================================================
# REGIME CLASSIFICATION
# =============================================================================
# Based on direction of each layer (+1, 0, -1)

REGIME_LABELS = {
    # Core regimes from Howell framework
    (1, 1, 1): 'Early Cycle - Max Bullish',
    (1, 1, -1): 'Late Easing - Recovery Underway',
    (1, -1, 1): 'Transmission Broken - CB Not Transmitting',
    (-1, 1, -1): 'Late Cycle - Tightening Hot Economy',
    (-1, -1, 1): 'Contraction - Tightening Weakening Economy',
    (-1, -1, -1): 'Maximum Contraction',
    # Intermediate states
    (1, 0, 1): 'Early Recovery',
    (1, 1, 0): 'Mid Easing',
    (1, 0, 0): 'CB Easing - Mixed Signals',
    (0, 1, 1): 'Private Expansion',
    (0, 1, -1): 'Late Private Expansion',
    (0, 0, 1): 'Economy Weakening',
    (-1, 0, -1): 'Stagflation Risk',
    (-1, 1, 0): 'Tightening - Private Resilient',
    (-1, 0, 0): 'CB Tightening - Mixed Signals',
    (0, -1, 1): 'Credit Contraction',
    (0, -1, -1): 'Late Cycle Stress',
    (0, 0, -1): 'Economy Overheating',
    (1, -1, -1): 'Policy Disconnect',
    (-1, 1, 1): 'Soft Landing Attempt',
    (1, -1, 0): 'Easing - Private Weak',
    (-1, -1, 0): 'Deep Contraction',
    (0, 1, 0): 'Private Neutral',
    (0, -1, 0): 'Private Weak',
    (1, 0, -1): 'Policy Lag',
    (-1, 0, 1): 'Recession Risk',
    (0, 0, 0): 'Neutral',
}

# =============================================================================
# AGGREGATION WEIGHTS
# =============================================================================

LAYER_WEIGHTS = {
    'L1': 0.40,   # CB Liquidity - primary driver
    'L2a': 0.35,  # Private/Wholesale - transmission
    'L2b': 0.25,  # Economic Reality - feedback
}

# Layer score ranges (for normalization)
LAYER_SCORE_RANGES = {
    'L1': (-4, 4),    # 4 scored indicators
    'L2a': (-6, 6),   # 6 scored indicators
    'L2b': (-6, 6),   # 6 scored indicators (was 7 but CPI used twice)
}

# =============================================================================
# ALL FRED SERIES TO FETCH
# =============================================================================

def get_all_fred_codes():
    """Return list of all unique FRED codes to fetch"""
    codes = set()
    for layer in [LAYER1_INDICATORS, LAYER2A_INDICATORS, LAYER2B_INDICATORS]:
        for key, config in layer.items():
            if config.get('fred_code') and not config.get('derived', False):
                codes.add(config['fred_code'])
    return sorted(list(codes))


FRED_SERIES = get_all_fred_codes()
# Expected: ['BAMLC0A0CM', 'BAMLH0A0HYM2OAS', 'BUSLOANS', 'CPIAUCSL', 'DFF',
#            'DGS10', 'DGS2', 'DTWEXBGS', 'EFFR', 'INDPRO', 'M2SL', 'NAPMPRIC',
#            'NFCI', 'RRPONTSYD', 'SOFR', 'TCU', 'TOTLL', 'UNRATE', 'VIXCLS',
#            'WALCL', 'WRMFSL', 'WTREGEN']
