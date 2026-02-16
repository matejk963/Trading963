"""
Futures contracts configuration
Contains contract metadata and ticker mappings for COT positioning analysis
"""

CONTRACTS = {
    # Currencies
    'DXY': {'name': 'DOLLAR INDEX (Combined)', 'category': 'Currencies', 'cftc_name': 'AGGREGATE_CURRENCIES'},  # Special aggregate
    '6E': {'name': 'EURO FX', 'category': 'Currencies', 'cftc_name': 'EURO FX - CHICAGO MERCANTILE EXCHANGE'},
    '6J': {'name': 'JAPANESE YEN', 'category': 'Currencies', 'cftc_name': 'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE'},
    '6B': {'name': 'BRITISH POUND', 'category': 'Currencies', 'cftc_name': ['BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE', 'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE']},
    '6C': {'name': 'CANADIAN DOLLAR', 'category': 'Currencies', 'cftc_name': 'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6S': {'name': 'SWISS FRANC', 'category': 'Currencies', 'cftc_name': 'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE'},
    '6A': {'name': 'AUSTRALIAN DOLLAR', 'category': 'Currencies', 'cftc_name': 'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6N': {'name': 'NEW ZEALAND DOLLAR', 'category': 'Currencies', 'cftc_name': 'NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6L': {'name': 'BRAZILIAN REAL', 'category': 'Currencies', 'cftc_name': 'BRAZILIAN REAL - CHICAGO MERCANTILE EXCHANGE'},

    # Indices
    'ES': {'name': 'S&P 500', 'category': 'Indices', 'cftc_name': 'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE'},
    'NQ': {'name': 'NASDAQ 100', 'category': 'Indices', 'cftc_name': 'NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE'},
    'YM': {'name': 'DOW JONES', 'category': 'Indices', 'cftc_name': 'DJIA Consolidated - CHICAGO BOARD OF TRADE'},
    'RTY': {'name': 'RUSSELL 2000', 'category': 'Indices', 'cftc_name': 'RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE'},
    'VX': {'name': 'VIX', 'category': 'Indices', 'cftc_name': 'VIX FUTURES - CBOE FUTURES EXCHANGE'},

    # Energy
    'CL': {'name': 'CRUDE OIL WTI', 'category': 'Energy', 'cftc_name': 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE'},
    'BZ': {'name': 'CRUDE OIL BRENT', 'category': 'Energy', 'cftc_name': 'BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE'},
    'NG': {'name': 'NATURAL GAS', 'category': 'Energy', 'cftc_name': 'NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE'},
    'RB': {'name': 'RBOB GASOLINE', 'category': 'Energy', 'cftc_name': 'GASOLINE RBOB - NEW YORK MERCANTILE EXCHANGE'},
    'HO': {'name': 'HEATING OIL', 'category': 'Energy', 'cftc_name': 'NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE'},

    # Metals
    'GC': {'name': 'GOLD', 'category': 'Metals', 'cftc_name': 'GOLD - COMMODITY EXCHANGE INC.'},
    'SI': {'name': 'SILVER', 'category': 'Metals', 'cftc_name': 'SILVER - COMMODITY EXCHANGE INC.'},
    'HG': {'name': 'COPPER', 'category': 'Metals', 'cftc_name': 'COPPER- #1 - COMMODITY EXCHANGE INC.'},
    'PL': {'name': 'PLATINUM', 'category': 'Metals', 'cftc_name': 'PLATINUM - NEW YORK MERCANTILE EXCHANGE'},
    'PA': {'name': 'PALLADIUM', 'category': 'Metals', 'cftc_name': 'PALLADIUM - NEW YORK MERCANTILE EXCHANGE'},

    # Grains
    'ZC': {'name': 'CORN', 'category': 'Grains', 'cftc_name': 'CORN - CHICAGO BOARD OF TRADE'},
    'ZW': {'name': 'WHEAT', 'category': 'Grains', 'cftc_name': 'WHEAT - CHICAGO BOARD OF TRADE'},
    'ZS': {'name': 'SOYBEANS', 'category': 'Grains', 'cftc_name': 'SOYBEANS - CHICAGO BOARD OF TRADE'},
    'ZM': {'name': 'SOYBEAN MEAL', 'category': 'Grains', 'cftc_name': 'SOYBEAN MEAL - CHICAGO BOARD OF TRADE'},
    'ZL': {'name': 'SOYBEAN OIL', 'category': 'Grains', 'cftc_name': 'SOYBEAN OIL - CHICAGO BOARD OF TRADE'},
    'ZO': {'name': 'OAT', 'category': 'Grains', 'cftc_name': 'OATS - CHICAGO BOARD OF TRADE'},
    'ZR': {'name': 'ROUGH RICE', 'category': 'Grains', 'cftc_name': 'ROUGH RICE - CHICAGO BOARD OF TRADE'},

    # Softs
    'KC': {'name': 'COFFEE', 'category': 'Softs', 'cftc_name': 'COFFEE C - ICE FUTURES U.S.'},
    'SB': {'name': 'SUGAR', 'category': 'Softs', 'cftc_name': 'SUGAR NO. 11 - ICE FUTURES U.S.'},
    'CC': {'name': 'COCOA', 'category': 'Softs', 'cftc_name': 'COCOA - ICE FUTURES U.S.'},
    'CT': {'name': 'COTTON', 'category': 'Softs', 'cftc_name': 'COTTON NO. 2 - ICE FUTURES U.S.'},
    'OJ': {'name': 'ORANGE JUICE', 'category': 'Softs', 'cftc_name': 'FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.'},
    'LBS': {'name': 'LUMBER', 'category': 'Softs', 'cftc_name': 'RANDOM LENGTH LUMBER - CHICAGO MERCANTILE EXCHANGE'},

    # Meats
    'LE': {'name': 'LIVE CATTLE', 'category': 'Meats', 'cftc_name': 'LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'GF': {'name': 'FEEDER CATTLE', 'category': 'Meats', 'cftc_name': 'FEEDER CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'HE': {'name': 'LEAN HOGS', 'category': 'Meats', 'cftc_name': 'LEAN HOGS - CHICAGO MERCANTILE EXCHANGE'},

    # Bonds (ordered by maturity: 2Y, 5Y, 10Y, 30Y)
    'ZT': {'name': '2-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'UST 2Y NOTE - CHICAGO BOARD OF TRADE', 'sort_order': 1},
    'ZF': {'name': '5-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'UST 5Y NOTE - CHICAGO BOARD OF TRADE', 'sort_order': 2},
    'ZN': {'name': '10-YEAR NOTE', 'category': 'Bonds', 'cftc_name': 'UST 10Y NOTE - CHICAGO BOARD OF TRADE', 'sort_order': 3},
    'ZB': {'name': '30-YEAR BOND', 'category': 'Bonds', 'cftc_name': 'UST BOND - CHICAGO BOARD OF TRADE', 'sort_order': 4},
}

# Ticker symbol mapping for price data (yfinance)
PRICE_TICKERS = {
    # Indices
    'ES': 'ES=F',    # E-mini S&P 500
    'NQ': 'NQ=F',    # E-mini NASDAQ-100
    'RTY': 'RTY=F',  # E-mini Russell 2000
    'YM': 'YM=F',    # E-mini Dow
    'DXY': 'DX-Y.NYB',  # US Dollar Index

    # Energies
    'CL': 'CL=F',    # Crude Oil WTI
    'RB': 'RB=F',    # RBOB Gasoline
    'HO': 'HO=F',    # Heating Oil
    'NG': 'NG=F',    # Natural Gas

    # Metals
    'GC': 'GC=F',    # Gold
    'SI': 'SI=F',    # Silver
    'HG': 'HG=F',    # Copper
    'PL': 'PL=F',    # Platinum

    # Grains
    'ZC': 'ZC=F',    # Corn
    'ZS': 'ZS=F',    # Soybeans
    'ZW': 'ZW=F',    # Wheat
    'ZL': 'ZL=F',    # Soybean Oil
    'ZM': 'ZM=F',    # Soybean Meal

    # Softs
    'KC': 'KC=F',    # Coffee
    'SB': 'SB=F',    # Sugar
    'CC': 'CC=F',    # Cocoa
    'CT': 'CT=F',    # Cotton
    'OJ': 'OJ=F',    # Orange Juice

    # Meats
    'LE': 'LE=F',    # Live Cattle
    'GF': 'GF=F',    # Feeder Cattle
    'HE': 'HE=F',    # Lean Hogs

    # Bonds
    'ZT': 'ZT=F',    # 2-Year Note
    'ZF': 'ZF=F',    # 5-Year Note
    'ZN': 'ZN=F',    # 10-Year Note
    'ZB': 'ZB=F',    # 30-Year Bond

    # Currencies (using FX pairs vs USD) - keys must match CONTRACTS dictionary
    'DXY': 'DX-Y.NYB',   # US Dollar Index
    '6E': 'EURUSD=X',    # Euro
    '6J': 'JPY=X',       # Japanese Yen (USD/JPY)
    '6B': 'GBPUSD=X',    # British Pound
    '6A': 'AUDUSD=X',    # Australian Dollar
    '6C': 'CAD=X',       # Canadian Dollar (USD/CAD)
    '6S': 'CHF=X',       # Swiss Franc (USD/CHF)
    '6N': 'NZDUSD=X',    # New Zealand Dollar
    '6L': 'BRL=X',       # Brazilian Real (USD/BRL)
}
