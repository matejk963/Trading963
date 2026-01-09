"""
Test Universal Parameters on All Contracts
- Signal Logic: Both_AND
- COT Lookback: 150 weeks
- Move Period: 8 weeks
- COT Thresholds: 10/90
- Move Thresholds: -45/+45
- Forward Periods: 4w and 26w
"""
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Contract definitions from app
CONTRACTS = {
    '6E': {'name': 'EURO FX', 'cftc_name': 'EURO FX - CHICAGO MERCANTILE EXCHANGE'},
    '6J': {'name': 'JAPANESE YEN', 'cftc_name': 'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE'},
    '6B': {'name': 'BRITISH POUND', 'cftc_name': 'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE'},
    '6S': {'name': 'SWISS FRANC', 'cftc_name': 'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE'},
    '6A': {'name': 'AUSTRALIAN DOLLAR', 'cftc_name': 'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6C': {'name': 'CANADIAN DOLLAR', 'cftc_name': 'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6L': {'name': 'BRAZILIAN REAL', 'cftc_name': 'BRAZILIAN REAL - CHICAGO MERCANTILE EXCHANGE'},
    'ES': {'name': 'S&P 500', 'cftc_name': 'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE'},
    'NQ': {'name': 'NASDAQ 100', 'cftc_name': 'NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE'},
    'YM': {'name': 'DOW JONES', 'cftc_name': 'DJIA Consolidated - CHICAGO BOARD OF TRADE'},
    'RTY': {'name': 'RUSSELL 2000', 'cftc_name': 'RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE'},
    'VX': {'name': 'VIX', 'cftc_name': 'VIX FUTURES - CBOE FUTURES EXCHANGE'},
    'CL': {'name': 'CRUDE OIL WTI', 'cftc_name': 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE'},
    'BZ': {'name': 'CRUDE OIL BRENT', 'cftc_name': 'BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE'},
    'NG': {'name': 'NATURAL GAS', 'cftc_name': 'NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE'},
    'RB': {'name': 'RBOB GASOLINE', 'cftc_name': 'GASOLINE RBOB - NEW YORK MERCANTILE EXCHANGE'},
    'HO': {'name': 'HEATING OIL', 'cftc_name': 'NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE'},
    'GC': {'name': 'GOLD', 'cftc_name': 'GOLD - COMMODITY EXCHANGE INC.'},
    'SI': {'name': 'SILVER', 'cftc_name': 'SILVER - COMMODITY EXCHANGE INC.'},
    'HG': {'name': 'COPPER', 'cftc_name': 'COPPER- #1 - COMMODITY EXCHANGE INC.'},
    'PL': {'name': 'PLATINUM', 'cftc_name': 'PLATINUM - NEW YORK MERCANTILE EXCHANGE'},
    'PA': {'name': 'PALLADIUM', 'cftc_name': 'PALLADIUM - NEW YORK MERCANTILE EXCHANGE'},
    'ZC': {'name': 'CORN', 'cftc_name': 'CORN - CHICAGO BOARD OF TRADE'},
    'ZW': {'name': 'WHEAT', 'cftc_name': 'WHEAT - CHICAGO BOARD OF TRADE'},
    'ZS': {'name': 'SOYBEANS', 'cftc_name': 'SOYBEANS - CHICAGO BOARD OF TRADE'},
    'ZM': {'name': 'SOYBEAN MEAL', 'cftc_name': 'SOYBEAN MEAL - CHICAGO BOARD OF TRADE'},
    'ZL': {'name': 'SOYBEAN OIL', 'cftc_name': 'SOYBEAN OIL - CHICAGO BOARD OF TRADE'},
    'ZO': {'name': 'OATS', 'cftc_name': 'OATS - CHICAGO BOARD OF TRADE'},
    'ZR': {'name': 'ROUGH RICE', 'cftc_name': 'ROUGH RICE - CHICAGO BOARD OF TRADE'},
    'KC': {'name': 'COFFEE', 'cftc_name': 'COFFEE C - ICE FUTURES U.S.'},
    'SB': {'name': 'SUGAR', 'cftc_name': 'SUGAR NO. 11 - ICE FUTURES U.S.'},
    'CC': {'name': 'COCOA', 'cftc_name': 'COCOA - ICE FUTURES U.S.'},
    'CT': {'name': 'COTTON', 'cftc_name': 'COTTON NO. 2 - ICE FUTURES U.S.'},
    'OJ': {'name': 'ORANGE JUICE', 'cftc_name': 'FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.'},
    'LBS': {'name': 'LUMBER', 'cftc_name': 'RANDOM LENGTH LUMBER - CHICAGO MERCANTILE EXCHANGE'},
    'LE': {'name': 'LIVE CATTLE', 'cftc_name': 'LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'GF': {'name': 'FEEDER CATTLE', 'cftc_name': 'FEEDER CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'HE': {'name': 'LEAN HOGS', 'cftc_name': 'LEAN HOGS - CHICAGO MERCANTILE EXCHANGE'},
    'ZT': {'name': '2-YEAR NOTE', 'cftc_name': 'UST 2Y NOTE - CHICAGO BOARD OF TRADE'},
    'ZF': {'name': '5-YEAR NOTE', 'cftc_name': 'UST 5Y NOTE - CHICAGO BOARD OF TRADE'},
    'ZN': {'name': '10-YEAR NOTE', 'cftc_name': 'UST 10Y NOTE - CHICAGO BOARD OF TRADE'},
    'ZB': {'name': '30-YEAR BOND', 'cftc_name': 'UST BOND - CHICAGO BOARD OF TRADE'},
}

PRICE_TICKERS = {
    'ES': 'ES=F', 'NQ': 'NQ=F', 'YM': 'YM=F', 'RTY': 'RTY=F', 'VX': 'VIX',
    '6E': 'EURUSD=X', '6J': 'JPYUSD=X', '6B': 'GBPUSD=X', '6S': 'CHFUSD=X',
    '6A': 'AUDUSD=X', '6C': 'CADUSD=X', '6L': 'BRLUSD=X',
    'GC': 'GC=F', 'SI': 'SI=F', 'HG': 'HG=F', 'PL': 'PL=F', 'PA': 'PA=F',
    'CL': 'CL=F', 'BZ': 'BZ=F', 'NG': 'NG=F', 'RB': 'RB=F', 'HO': 'HO=F',
    'ZC': 'ZC=F', 'ZW': 'ZW=F', 'ZS': 'ZS=F', 'ZM': 'ZM=F', 'ZL': 'ZL=F', 'ZO': 'ZO=F', 'ZR': 'ZR=F',
    'KC': 'KC=F', 'SB': 'SB=F', 'CC': 'CC=F', 'CT': 'CT=F', 'OJ': 'OJ=F', 'LBS': 'LBS=F',
    'LE': 'LE=F', 'GF': 'GF=F', 'HE': 'HE=F',
    'ZT': 'ZT=F', 'ZF': 'ZF=F', 'ZN': 'ZN=F', 'ZB': 'ZB=F'
}

# Universal parameters
COT_LOOKBACK = 150
MOVE_PERIOD = 8
COT_LOW = 10
COT_HIGH = 90
MOVE_LOW = -45
MOVE_HIGH = 45

print("="*100)
print("TESTING UNIVERSAL PARAMETERS ON ALL CONTRACTS")
print("="*100)
print(f"\nParameters:")
print(f"  Signal Logic:    Both_AND")
print(f"  COT Lookback:    {COT_LOOKBACK} weeks")
print(f"  Move Period:     {MOVE_PERIOD} weeks")
print(f"  COT Thresholds:  {COT_LOW}/{COT_HIGH}")
print(f"  Move Thresholds: {MOVE_LOW}/{MOVE_HIGH}")
print(f"  Forward Periods: 4w and 26w")
print("="*100)

# Load COT data
print("\nLoading COT data...")
cot_df = pd.read_csv('data/cftc/legacy_long_format_combined_2005_2025.csv')

# Normalize column names
cot_df.columns = [col.replace('_(All)', '_All').replace('_(Old)', '_Old').replace('(', '').replace(')', '')
                  for col in cot_df.columns]

# Remove duplicate columns (keep first occurrence)
cot_df = cot_df.loc[:, ~cot_df.columns.duplicated()]

cot_df['As_of_Date_in_Form_YYYY-MM-DD'] = pd.to_datetime(cot_df['As_of_Date_in_Form_YYYY-MM-DD'])

results = []

for contract_code, contract_info in CONTRACTS.items():
    print(f"\n{'='*100}")
    print(f"Processing {contract_code} - {contract_info['name']}")
    print(f"{'='*100}")

    # Get COT data for this contract
    contract_cot = cot_df[cot_df['Market_and_Exchange_Names'] == contract_info['cftc_name']].copy()

    if len(contract_cot) == 0:
        print(f"  ⚠ No COT data found")
        continue

    contract_cot = contract_cot.sort_values('As_of_Date_in_Form_YYYY-MM-DD').reset_index(drop=True)

    # Calculate Net % of OI
    total_oi = contract_cot['Commercial_Positions-Long_All'] + contract_cot['Commercial_Positions-Short_All']
    contract_cot['Net_Pct_OI'] = ((contract_cot['Commercial_Positions-Long_All'] -
                                   contract_cot['Commercial_Positions-Short_All']) / total_oi) * 100

    # Calculate COT Index
    contract_cot['Min_Lookback'] = contract_cot['Net_Pct_OI'].rolling(window=COT_LOOKBACK, min_periods=1).min()
    contract_cot['Max_Lookback'] = contract_cot['Net_Pct_OI'].rolling(window=COT_LOOKBACK, min_periods=1).max()

    contract_cot['COT_Index'] = ((contract_cot['Net_Pct_OI'] - contract_cot['Min_Lookback']) /
                                 (contract_cot['Max_Lookback'] - contract_cot['Min_Lookback'])) * 100

    # Calculate COT Move Index
    contract_cot['COT_Move'] = contract_cot['COT_Index'] - contract_cot['COT_Index'].shift(MOVE_PERIOD)

    # Get price data
    ticker = PRICE_TICKERS.get(contract_code)
    if not ticker:
        print(f"  ⚠ No price ticker found")
        continue

    try:
        price_data = yf.download(ticker, start='2010-01-01', end=datetime.now().strftime('%Y-%m-%d'),
                                progress=False)
        if len(price_data) == 0:
            print(f"  ⚠ No price data downloaded")
            continue

        price_data = price_data[['Close']].reset_index()
        price_data.columns = ['Date', 'Close']
        price_data['Date'] = pd.to_datetime(price_data['Date'])

    except Exception as e:
        print(f"  ⚠ Error downloading price data: {e}")
        continue

    # Merge COT and price data
    merged = pd.merge_asof(contract_cot.sort_values('As_of_Date_in_Form_YYYY-MM-DD'),
                          price_data.sort_values('Date'),
                          left_on='As_of_Date_in_Form_YYYY-MM-DD',
                          right_on='Date',
                          direction='forward')

    if len(merged) < COT_LOOKBACK + MOVE_PERIOD + 26:
        print(f"  ⚠ Insufficient data after merge")
        continue

    # Test both forward periods
    for forward_weeks in [4, 26]:
        test_df = merged.copy()

        # Calculate forward return
        test_df['Future_Price'] = test_df['Close'].shift(-forward_weeks)
        test_df['Forward_Return'] = ((test_df['Future_Price'] - test_df['Close']) / test_df['Close']) * 100

        # Generate signals - Both_AND logic
        test_df['Signal'] = 0
        test_df.loc[(test_df['COT_Index'] >= COT_HIGH) & (test_df['COT_Move'] >= MOVE_HIGH), 'Signal'] = 1
        test_df.loc[(test_df['COT_Index'] <= COT_LOW) & (test_df['COT_Move'] <= MOVE_LOW), 'Signal'] = -1

        # Calculate returns at signals
        signal_dates = test_df[test_df['Signal'] != 0].copy()
        signal_dates['Trade_Return'] = signal_dates['Signal'] * signal_dates['Forward_Return']

        # Remove NaN returns
        valid_returns = signal_dates['Trade_Return'].dropna()

        if len(valid_returns) == 0:
            print(f"  {forward_weeks}w: No valid signals")
            continue

        # Calculate metrics
        avg_return = valid_returns.mean()
        win_rate = (valid_returns > 0).mean() * 100
        sharpe = (valid_returns.mean() / valid_returns.std()) if valid_returns.std() > 0 else 0

        # Buy/Sell breakdown
        buy_signals = signal_dates[signal_dates['Signal'] == 1]['Trade_Return'].dropna()
        sell_signals = signal_dates[signal_dates['Signal'] == -1]['Trade_Return'].dropna()

        buy_avg = buy_signals.mean() if len(buy_signals) > 0 else 0
        buy_wr = (buy_signals > 0).mean() * 100 if len(buy_signals) > 0 else 0
        sell_avg = sell_signals.mean() if len(sell_signals) > 0 else 0
        sell_wr = (sell_signals > 0).mean() * 100 if len(sell_signals) > 0 else 0

        print(f"  {forward_weeks}w: Sharpe={sharpe:.3f}, Return={avg_return:.2f}%, WinRate={win_rate:.1f}%, Signals={len(valid_returns)}")

        results.append({
            'Contract': contract_code,
            'Name': contract_info['name'],
            'Forward_Period': f'{forward_weeks}w',
            'Sharpe': sharpe,
            'Avg_Return': avg_return,
            'Win_Rate': win_rate,
            'Total_Signals': len(valid_returns),
            'Buy_Signals': len(buy_signals),
            'Sell_Signals': len(sell_signals),
            'Buy_Avg_Return': buy_avg,
            'Buy_Win_Rate': buy_wr,
            'Sell_Avg_Return': sell_avg,
            'Sell_Win_Rate': sell_wr
        })

# Save results
results_df = pd.DataFrame(results)
results_df.to_csv('sandbox/universal_parameters_results.csv', index=False)

print("\n" + "="*100)
print("✓ TESTING COMPLETE")
print("="*100)
print(f"\nProcessed {len(results_df)//2} contracts with 2 forward periods each")
print(f"Total configurations tested: {len(results_df)}")
print(f"\nResults saved to: sandbox/universal_parameters_results.csv")
