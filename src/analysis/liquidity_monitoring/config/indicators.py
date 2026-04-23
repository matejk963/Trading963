"""
Liquidity Indicators Configuration
Based on Michael Howell's 3-layer Global Liquidity Index framework
Combined with Mark Boucher's Austrian Liquidity Cycle (The Hedge Fund Edge, 1999)

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
# Two independent CB dimensions:
#   1. Quantity of money injected (Net Liquidity)
#   2. Price of money (Real Policy Rate)
# Score range: -2 to +2

LAYER1_INDICATORS = {
    'fed_balance_sheet': {
        'fred_code': 'WALCL',
        'name': 'Fed Balance Sheet',
        'description': 'Total Assets of Federal Reserve',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'component',
    },
    'tga': {
        'fred_code': 'WTREGEN',
        'name': 'Treasury General Account',
        'description': 'Treasury cash balance at Fed - drains reserves when rising',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'component',
    },
    'rrp': {
        'fred_code': 'RRPONTSYD',
        'name': 'Reverse Repo Facility',
        'description': 'ON RRP usage - liquidity drain when high',
        'frequency': 'daily',
        'units': 'billions_usd',
        'signal_type': 'component',
    },
    'fed_funds': {
        'fred_code': 'DFF',
        'name': 'Fed Funds Rate',
        'description': 'Effective Federal Funds Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',
    },
    'core_pce': {
        'fred_code': 'PCEPILFE',
        'name': 'Core PCE Price Index',
        'description': "Fed's preferred inflation measure for real rate calculation",
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'component',
    },
    'cpi': {
        'fred_code': 'CPIAUCSL',
        'name': 'CPI All Items',
        'description': 'Consumer Price Index - cross-check; used in L2b',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'component',
    },
    'dgs10': {
        'fred_code': 'DGS10',
        'name': '10-Year Treasury',
        'description': '10-Year Treasury Constant Maturity Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',
    },
    'dgs2': {
        'fred_code': 'DGS2',
        'name': '2-Year Treasury',
        'description': '2-Year Treasury Constant Maturity Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',
    },
    'tips_2y': {
        'fred_code': 'DFII2',
        'name': '2Y TIPS Real Yield',
        'description': 'Market-implied real rate - confirmation signal (not scored)',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',
    },
    # Derived indicator 1: Net Liquidity
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
    # Derived indicator 2: Real Policy Rate
    'real_policy_rate': {
        'fred_code': None,
        'name': 'Real Policy Rate',
        'description': 'DFF - Core PCE YoY. Negative = CB subsidising borrowing = bullish',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 0,    # Negative real rate = bullish
        'bearish_threshold': 1.0,  # >1% and rising = bearish
        'invert': True,            # Lower real rate = more bullish
        'derived': True,
        'formula': 'DFF - PCEPILFE_YoY',
        'zlb_weight': 0.5,        # Down-weight when at zero lower bound
    },
}

# =============================================================================
# LAYER 2a: PRIVATE SECTOR / WHOLESALE LIQUIDITY
# =============================================================================
# Amplitude and transmission of CB policy through private system
# Score range: -11 to +11

LAYER2A_INDICATORS = {
    'rrp_direction': {
        'fred_code': 'RRPONTSYD',
        'name': 'RRP Direction',
        'description': 'Falling RRP = cash entering private system',
        'frequency': 'daily',
        'units': 'billions_usd',
        'signal_type': 'roc_4w',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': True,  # Falling RRP = bullish
    },
    'sofr_effr_spread': {
        'fred_code': None,
        'name': 'SOFR-EFFR Spread',
        'description': 'Repo stress indicator',
        'frequency': 'daily',
        'units': 'basis_points',
        'signal_type': 'level',
        'bullish_threshold': 5,
        'bearish_threshold': 15,
        'invert': True,
        'derived': True,
        'formula': '(SOFR - EFFR) * 100',
    },
    'mmf_assets': {
        'fred_code': 'WRMFSL',
        'name': 'MMF Total Assets (All)',
        'description': 'Total Money Market Fund Assets - retail + institutional',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
    },
    'mmf_deployed': {
        'fred_code': None,
        'name': 'MMF Deployed Cash',
        'description': 'WRMFSL - RRPONTSYD = cash in private markets (not parked at Fed)',
        'frequency': 'weekly',
        'units': 'billions_usd',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
        'derived': True,
        'formula': 'WRMFSL - RRPONTSYD',
    },
    'hy_spread': {
        'fred_code': 'BAMLH0A0HYM2',
        'name': 'HY Credit Spread',
        'description': 'ICE BofA US High Yield OAS',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 4.0,
        'bearish_threshold': 6.0,
        'invert': True,
    },
    'ig_spread': {
        'fred_code': 'BAMLC0A0CM',
        'name': 'IG Credit Spread',
        'description': 'ICE BofA US Corporate OAS',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'level',
        'bullish_threshold': 1.0,
        'bearish_threshold': 2.0,
        'invert': True,
    },
    'vix': {
        'fred_code': 'VIXCLS',
        'name': 'VIX',
        'description': 'CBOE Volatility Index - collateral haircut proxy',
        'frequency': 'daily',
        'units': 'index',
        'signal_type': 'level',
        'bullish_threshold': 16,
        'bearish_threshold': 25,
        'invert': True,  # High VIX = haircuts expanding = bearish
    },
    'nfci': {
        'fred_code': 'NFCI',
        'name': 'Chicago Fed NFCI',
        'description': 'National Financial Conditions Index (negative = loose)',
        'frequency': 'weekly',
        'units': 'index',
        'signal_type': 'level',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': True,
    },
    'sofr': {
        'fred_code': 'SOFR',
        'name': 'SOFR',
        'description': 'Secured Overnight Financing Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',
    },
    'effr': {
        'fred_code': 'EFFR',
        'name': 'EFFR',
        'description': 'Effective Federal Funds Rate',
        'frequency': 'daily',
        'units': 'percent',
        'signal_type': 'component',
    },
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
        'bullish_threshold': 78,
        'neutral_high': 81.5,
        'bearish_threshold': 81.5,
        'invert': True,
        'counterintuitive': True,
    },
    'industrial_prod': {
        'fred_code': 'INDPRO',
        'name': 'Industrial Production',
        'description': 'Industrial Production Index',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'roc_12m',
        'bullish_threshold': 5,
        'bearish_threshold': 7,
        'invert': True,
        'counterintuitive': True,
    },
    'unemployment': {
        'fred_code': 'UNRATE',
        'name': 'Unemployment Rate',
        'description': 'Civilian Unemployment Rate',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'roc_29m',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
        'counterintuitive': True,
    },
    'cpi_level': {
        'fred_code': 'CPIAUCSL',
        'name': 'CPI Level',
        'description': 'CPI YoY for inflation assessment',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'yoy',
        'bullish_threshold': 3.2,
        'neutral_high': 5.0,
        'bearish_threshold': 5.0,
        'invert': True,
        'counterintuitive': True,
    },
    'cpi_momentum': {
        'fred_code': 'CPIAUCSL',
        'name': 'CPI Momentum',
        'description': '3-month annualized vs 12-month (deceleration signal)',
        'frequency': 'monthly',
        'units': 'percent',
        'signal_type': 'momentum',
        'bullish_threshold': 0,
        'bearish_threshold': 0,
        'invert': False,
        'counterintuitive': True,
        'derived': True,
        'formula': 'CPI_3M_ANN - CPI_12M',
    },
    'ism_prices': {
        'fred_code': 'NAPMPRIC',
        'name': 'ISM Prices Paid',
        'description': 'ISM Manufacturing Prices Paid - Boucher sensitive materials 18m ROC',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'roc_18m',
        'bullish_threshold': 18,
        'bearish_threshold': 25,
        'invert': True,
        'counterintuitive': True,
    },
    'ppi_commodities': {
        'fred_code': 'PPIACO',
        'name': 'PPI All Commodities',
        'description': 'Producer Price Index - All Commodities. ROC: decelerating = bullish',
        'frequency': 'monthly',
        'units': 'index',
        'signal_type': 'roc_12m',
        'bullish_threshold': 0,
        'bearish_threshold': 5,
        'invert': True,
        'counterintuitive': True,
    },
}

# =============================================================================
# REGIME CLASSIFICATION
# =============================================================================

REGIME_LABELS = {
    (1, 1, 1): 'Early Cycle - Max Bullish',
    (1, 1, -1): 'Late Easing - Recovery Underway',
    (1, -1, 1): 'Transmission Broken - CB Not Transmitting',
    (-1, 1, -1): 'Late Cycle - Tightening Hot Economy',
    (-1, -1, 1): 'Contraction - Tightening Weakening Economy',
    (-1, -1, -1): 'Maximum Contraction',
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
    'L1': 0.40,
    'L2a': 0.35,
    'L2b': 0.25,
}

LAYER_SCORE_RANGES = {
    'L1': (-2, 2),
    'L2a': (-11, 11),
    'L2b': (-7, 7),
}

# =============================================================================
# TRANSMISSION CHAIN STAGES
# =============================================================================

TRANSMISSION_STAGES = {
    1: {
        'name': 'CB Impulse Created',
        'question': 'Did the CB inject?',
        'indicators': {
            'net_liquidity': {'source': 'L1', 'signal': 'Positive = injecting'},
            'real_policy_rate': {'source': 'L1', 'signal': 'Negative = accommodative'},
            'tga_direction': {'fred_code': 'WTREGEN', 'signal_type': 'roc_4w', 'invert': True,
                              'signal': 'Falling = releasing cash'},
        }
    },
    2: {
        'name': 'Wholesale Activation',
        'question': 'Is the plumbing turning over?',
        'indicators': {
            'rrp_direction': {'source': 'L2a', 'signal': 'Falling = cash leaving Fed'},
            'sofr_effr_spread': {'source': 'L2a', 'signal': '<5bp = healthy'},
            'mmf_deployed': {'source': 'L2a', 'signal': 'Rising = cash in private system'},
        }
    },
    3: {
        'name': 'Risk Appetite',
        'question': 'Is the market willing to extend credit?',
        'indicators': {
            'hy_spread': {'source': 'L2a', 'signal': 'Compressing = risk appetite'},
            'ig_spread': {'source': 'L2a', 'signal': 'Confirmation'},
            'vix': {'source': 'L2a', 'signal': 'Falling = haircuts contracting'},
            'nfci': {'source': 'L2a', 'signal': 'Negative = loose conditions'},
        }
    },
    4: {
        'name': 'Bank Credit Expansion',
        'question': 'Is it crossing into the real economy?',
        'indicators': {
            'bank_credit': {'source': 'L2a', 'signal': 'Accelerating'},
            'ci_loans': {'source': 'L2a', 'signal': 'Business credit drawing'},
            'm2': {'source': 'L2a', 'signal': 'Money supply expanding'},
        }
    },
    5: {
        'name': 'Asset Price Response',
        'question': 'Are markets pricing in the liquidity?',
        'indicators': {
            'sp500': {'fred_code': 'SP500', 'signal_type': 'roc_12m',
                      'signal': 'Equity repricing'},
            'gold': {'fred_code': 'GOLDAMGBD228NLBM', 'signal_type': 'roc_12m',
                     'signal': 'Real rate inverse'},
        }
    },
    6: {
        'name': 'Real Economy Response',
        'question': 'Has it reached the ground?',
        'indicators': {
            'industrial_prod': {'source': 'L2b', 'invert_for_stage': True,
                                'signal': 'Accelerating'},
            'capacity_util': {'source': 'L2b', 'invert_for_stage': True,
                              'signal': 'Rising toward 80%'},
            'unemployment': {'source': 'L2b', 'invert_for_stage': True,
                             'signal': 'Falling = demand absorbing labor'},
        }
    },
    7: {
        'name': 'Cycle Reversal Warning',
        'question': 'Is the CB about to tighten?',
        'indicators': {
            'cpi_momentum': {'source': 'L2b', 'signal': 'Positive = acceleration'},
            'cpi_level': {'source': 'L2b', 'signal': '>3.2% = pressure building'},
            'ism_prices': {'source': 'L2b', 'signal': '>18% = upstream inflation'},
            'capacity_util_hot': {'source': 'L2b', 'signal': '>81.5% = running hot'},
        }
    },
}

# FRED codes needed only for Stage 5 (not in main layer configs)
STAGE_FRED_CODES = ['SP500', 'GOLDAMGBD228NLBM']

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
    # Add stage-specific codes
    for code in STAGE_FRED_CODES:
        codes.add(code)
    return sorted(list(codes))


FRED_SERIES = get_all_fred_codes()
