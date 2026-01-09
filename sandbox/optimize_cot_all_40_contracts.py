"""
COT Index Parameter Optimization for ALL 40 Contracts from App
Uses exact contract mappings from streamlit_app.py
"""
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Contract definitions from app
CONTRACTS = {
    # Currencies
    'DXY': {'name': 'DOLLAR INDEX', 'cftc_name': 'AGGREGATE_CURRENCIES'},
    '6E': {'name': 'EURO FX', 'cftc_name': 'EURO FX - CHICAGO MERCANTILE EXCHANGE'},
    '6J': {'name': 'JAPANESE YEN', 'cftc_name': 'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE'},
    '6B': {'name': 'BRITISH POUND', 'cftc_name': 'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE'},
    '6C': {'name': 'CANADIAN DOLLAR', 'cftc_name': 'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6S': {'name': 'SWISS FRANC', 'cftc_name': 'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE'},
    '6A': {'name': 'AUSTRALIAN DOLLAR', 'cftc_name': 'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6N': {'name': 'NEW ZEALAND DOLLAR', 'cftc_name': 'NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE'},
    '6L': {'name': 'BRAZILIAN REAL', 'cftc_name': 'BRAZILIAN REAL - CHICAGO MERCANTILE EXCHANGE'},
    # Indices
    'ES': {'name': 'S&P 500', 'cftc_name': 'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE'},
    'NQ': {'name': 'NASDAQ 100', 'cftc_name': 'NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE'},
    'YM': {'name': 'DOW JONES', 'cftc_name': 'DJIA Consolidated - CHICAGO BOARD OF TRADE'},
    'RTY': {'name': 'RUSSELL 2000', 'cftc_name': 'RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE'},
    'VX': {'name': 'VIX', 'cftc_name': 'VIX FUTURES - CBOE FUTURES EXCHANGE'},
    # Energy
    'CL': {'name': 'CRUDE OIL WTI', 'cftc_name': 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE'},
    'BZ': {'name': 'CRUDE OIL BRENT', 'cftc_name': 'BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE'},
    'NG': {'name': 'NATURAL GAS', 'cftc_name': 'NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE'},
    'RB': {'name': 'RBOB GASOLINE', 'cftc_name': 'GASOLINE RBOB - NEW YORK MERCANTILE EXCHANGE'},
    'HO': {'name': 'HEATING OIL', 'cftc_name': 'NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE'},
    # Metals
    'GC': {'name': 'GOLD', 'cftc_name': 'GOLD - COMMODITY EXCHANGE INC.'},
    'SI': {'name': 'SILVER', 'cftc_name': 'SILVER - COMMODITY EXCHANGE INC.'},
    'HG': {'name': 'COPPER', 'cftc_name': 'COPPER- #1 - COMMODITY EXCHANGE INC.'},
    'PL': {'name': 'PLATINUM', 'cftc_name': 'PLATINUM - NEW YORK MERCANTILE EXCHANGE'},
    'PA': {'name': 'PALLADIUM', 'cftc_name': 'PALLADIUM - NEW YORK MERCANTILE EXCHANGE'},
    # Grains
    'ZC': {'name': 'CORN', 'cftc_name': 'CORN - CHICAGO BOARD OF TRADE'},
    'ZW': {'name': 'WHEAT', 'cftc_name': 'WHEAT - CHICAGO BOARD OF TRADE'},
    'ZS': {'name': 'SOYBEANS', 'cftc_name': 'SOYBEANS - CHICAGO BOARD OF TRADE'},
    'ZM': {'name': 'SOYBEAN MEAL', 'cftc_name': 'SOYBEAN MEAL - CHICAGO BOARD OF TRADE'},
    'ZL': {'name': 'SOYBEAN OIL', 'cftc_name': 'SOYBEAN OIL - CHICAGO BOARD OF TRADE'},
    'ZO': {'name': 'OATS', 'cftc_name': 'OATS - CHICAGO BOARD OF TRADE'},
    'ZR': {'name': 'ROUGH RICE', 'cftc_name': 'ROUGH RICE - CHICAGO BOARD OF TRADE'},
    # Softs
    'KC': {'name': 'COFFEE', 'cftc_name': 'COFFEE C - ICE FUTURES U.S.'},
    'SB': {'name': 'SUGAR', 'cftc_name': 'SUGAR NO. 11 - ICE FUTURES U.S.'},
    'CC': {'name': 'COCOA', 'cftc_name': 'COCOA - ICE FUTURES U.S.'},
    'CT': {'name': 'COTTON', 'cftc_name': 'COTTON NO. 2 - ICE FUTURES U.S.'},
    'OJ': {'name': 'ORANGE JUICE', 'cftc_name': 'FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.'},
    'LBS': {'name': 'LUMBER', 'cftc_name': 'RANDOM LENGTH LUMBER - CHICAGO MERCANTILE EXCHANGE'},
    # Meats
    'LE': {'name': 'LIVE CATTLE', 'cftc_name': 'LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'GF': {'name': 'FEEDER CATTLE', 'cftc_name': 'FEEDER CATTLE - CHICAGO MERCANTILE EXCHANGE'},
    'HE': {'name': 'LEAN HOGS', 'cftc_name': 'LEAN HOGS - CHICAGO MERCANTILE EXCHANGE'},
    # Bonds
    'ZT': {'name': '2-YEAR NOTE', 'cftc_name': 'UST 2Y NOTE - CHICAGO BOARD OF TRADE'},
    'ZF': {'name': '5-YEAR NOTE', 'cftc_name': 'UST 5Y NOTE - CHICAGO BOARD OF TRADE'},
    'ZN': {'name': '10-YEAR NOTE', 'cftc_name': 'UST 10Y NOTE - CHICAGO BOARD OF TRADE'},
    'ZB': {'name': '30-YEAR BOND', 'cftc_name': 'UST BOND - CHICAGO BOARD OF TRADE'},
}

# Price tickers from app
PRICE_TICKERS = {
    'ES': 'ES=F', 'NQ': 'NQ=F', 'RTY': 'RTY=F', 'YM': 'YM=F',
    'CL': 'CL=F', 'RB': 'RB=F', 'HO': 'HO=F', 'NG': 'NG=F', 'BZ': 'BZ=F',
    'GC': 'GC=F', 'SI': 'SI=F', 'HG': 'HG=F', 'PL': 'PL=F', 'PA': 'PA=F',
    'ZC': 'ZC=F', 'ZS': 'ZS=F', 'ZW': 'ZW=F', 'ZL': 'ZL=F', 'ZM': 'ZM=F',
    'ZO': 'ZO=F', 'ZR': 'ZR=F',
    'KC': 'KC=F', 'SB': 'SB=F', 'CC': 'CC=F', 'CT': 'CT=F', 'OJ': 'OJ=F',
    'LE': 'LE=F', 'GF': 'GF=F', 'HE': 'HE=F', 'LBS': 'LBS=F',
    'ZT': 'ZT=F', 'ZF': 'ZF=F', 'ZN': 'ZN=F', 'ZB': 'ZB=F',
    'DXY': 'DX-Y.NYB', '6E': 'EURUSD=X', '6J': 'JPY=X', '6B': 'GBPUSD=X',
    '6A': 'AUDUSD=X', '6C': 'CAD=X', '6S': 'CHF=X', '6N': 'NZDUSD=X', '6L': 'BRL=X',
    'VX': '^VIX'
}

print("="*80)
print("COT INDEX PARAMETER OPTIMIZATION - ALL 40 CONTRACTS")
print("="*80)
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Load CoT data
print("[1/3] Loading CoT data...")
df = pd.read_csv('data/cftc/legacy_long_format_combined_2005_2025.csv', low_memory=False)
df['Date'] = pd.to_datetime(df['As_of_Date_in_Form_YYYY-MM-DD'])
df = df.sort_values('Date')
print(f"   ✓ Loaded {len(df)} total CoT records")

# Parameter grid
param_grid = {
    'cot_lookback': [52, 78, 104, 156, 208],
    'move_period': [4, 6, 8, 12, 16],
    'cot_thresholds': [(5, 95), (10, 90), (15, 85), (20, 80)],
    'move_thresholds': [(-30, 30), (-40, 40), (-50, 50)]
}
forward_periods = {'4w': 4, '13w': 13, '26w': 26}

print(f"\n[2/3] Parameter grid: {len(param_grid['cot_lookback']) * len(param_grid['move_period']) * len(param_grid['cot_thresholds']) * len(param_grid['move_thresholds'])} combinations per contract")

# Process contracts
print(f"\n[3/3] Processing {len(CONTRACTS)} contracts...\n")

all_results = []
contract_summary = []
processed_count = 0
skipped_count = 0

for contract_code, contract_info in CONTRACTS.items():
    print(f"[{processed_count + skipped_count + 1}/{len(CONTRACTS)}] {contract_code} - {contract_info['name']}")

    # Filter CoT data
    cftc_name = contract_info['cftc_name']
    contract_df = df[df['Market_and_Exchange_Names'] == cftc_name].copy()

    if len(contract_df) == 0:
        print(f"   ✗ No CoT data found for: {cftc_name}")
        skipped_count += 1
        continue

    print(f"   ✓ Found {len(contract_df)} CoT records ({contract_df['Date'].min().strftime('%Y-%m')} to {contract_df['Date'].max().strftime('%Y-%m')})")

    # Calculate positioning
    contract_df['Total_OI'] = (contract_df['Commercial_Positions-Long_(All)'] +
                                contract_df['Noncommercial_Positions-Long_(All)'] +
                                contract_df['Nonreportable_Positions-Long_(All)'])
    contract_df['Commercial_Net'] = (contract_df['Commercial_Positions-Long_(All)'] -
                                     contract_df['Commercial_Positions-Short_(All)'])
    contract_df['Net_Pct_OI'] = (contract_df['Commercial_Net'] / contract_df['Total_OI']) * 100

    # Fetch price data
    ticker = PRICE_TICKERS.get(contract_code)
    if not ticker:
        print(f"   ✗ No price ticker mapping")
        skipped_count += 1
        continue

    print(f"   → Fetching prices: {ticker}...")
    try:
        start_date = contract_df['Date'].min() - timedelta(days=30)
        price_data = yf.download(ticker, start=start_date, end=datetime.now(), progress=False)

        if price_data.empty:
            print(f"   ✗ No price data")
            skipped_count += 1
            continue

        if isinstance(price_data.columns, pd.MultiIndex):
            price_data.columns = price_data.columns.get_level_values(0)

        price_df = price_data[['Close']].copy()
        price_df = price_df.reset_index()
        price_df.columns = ['Date', 'Price']

        contract_df = contract_df.merge(price_df, on='Date', how='left')
        contract_df['Price'] = contract_df['Price'].fillna(method='ffill')

        if contract_df['Price'].isna().all():
            print(f"   ✗ No valid prices after merge")
            skipped_count += 1
            continue

        print(f"   ✓ Merged {len(price_df)} price records")

    except Exception as e:
        print(f"   ✗ Price error: {str(e)}")
        skipped_count += 1
        continue

    # Calculate forward returns
    for period_name, weeks in forward_periods.items():
        contract_df[f'Forward_Return_{period_name}'] = (
            (contract_df['Price'].shift(-weeks) / contract_df['Price'] - 1) * 100
        )

    # Run optimization
    print(f"   → Optimizing parameters...")
    contract_results = []

    for cot_lb in param_grid['cot_lookback']:
        for move_pd in param_grid['move_period']:
            for cot_thresh in param_grid['cot_thresholds']:
                for move_thresh in param_grid['move_thresholds']:

                    test_df = contract_df.copy()
                    test_df['Min'] = test_df['Net_Pct_OI'].rolling(window=cot_lb, min_periods=cot_lb//2).min()
                    test_df['Max'] = test_df['Net_Pct_OI'].rolling(window=cot_lb, min_periods=cot_lb//2).max()
                    test_df['COT_Index'] = ((test_df['Net_Pct_OI'] - test_df['Min']) /
                                           (test_df['Max'] - test_df['Min'])) * 100
                    test_df['COT_Move'] = test_df['COT_Index'] - test_df['COT_Index'].shift(move_pd)

                    cot_low, cot_high = cot_thresh
                    move_low, move_high = move_thresh

                    # Generate signals
                    test_df['Signal_COT_Only'] = 0
                    test_df.loc[test_df['COT_Index'] >= cot_high, 'Signal_COT_Only'] = 1
                    test_df.loc[test_df['COT_Index'] <= cot_low, 'Signal_COT_Only'] = -1

                    test_df['Signal_Move_Only'] = 0
                    test_df.loc[test_df['COT_Move'] >= move_high, 'Signal_Move_Only'] = 1
                    test_df.loc[test_df['COT_Move'] <= move_low, 'Signal_Move_Only'] = -1

                    test_df['Signal_Both_AND'] = 0
                    test_df.loc[(test_df['COT_Index'] >= cot_high) & (test_df['COT_Move'] >= move_high),
                               'Signal_Both_AND'] = 1
                    test_df.loc[(test_df['COT_Index'] <= cot_low) & (test_df['COT_Move'] <= move_low),
                               'Signal_Both_AND'] = -1

                    test_df['Signal_Conditional'] = 0
                    test_df.loc[test_df['COT_Index'] >= cot_high, 'Signal_Conditional'] = 1
                    test_df.loc[test_df['COT_Index'] <= cot_low, 'Signal_Conditional'] = -1
                    neutral_mask = (test_df['COT_Index'] > cot_low) & (test_df['COT_Index'] < cot_high)
                    test_df.loc[neutral_mask & (test_df['COT_Move'] >= move_high * 1.5), 'Signal_Conditional'] = 1
                    test_df.loc[neutral_mask & (test_df['COT_Move'] <= move_low * 1.5), 'Signal_Conditional'] = -1

                    # Evaluate
                    for period_name in forward_periods.keys():
                        fwd_col = f'Forward_Return_{period_name}'

                        for signal_name in ['Signal_COT_Only', 'Signal_Move_Only', 'Signal_Both_AND', 'Signal_Conditional']:
                            buy_signals = test_df[test_df[signal_name] == 1]
                            sell_signals = test_df[test_df[signal_name] == -1]

                            if len(buy_signals) > 0:
                                buy_returns = buy_signals[fwd_col].dropna()
                                buy_avg = buy_returns.mean() if len(buy_returns) > 0 else np.nan
                                buy_winrate = (buy_returns > 0).mean() * 100 if len(buy_returns) > 0 else np.nan
                                buy_count = len(buy_returns)
                            else:
                                buy_avg, buy_winrate, buy_count = np.nan, np.nan, 0

                            if len(sell_signals) > 0:
                                sell_returns = -sell_signals[fwd_col].dropna()
                                sell_avg = sell_returns.mean() if len(sell_returns) > 0 else np.nan
                                sell_winrate = (sell_returns > 0).mean() * 100 if len(sell_returns) > 0 else np.nan
                                sell_count = len(sell_returns)
                            else:
                                sell_avg, sell_winrate, sell_count = np.nan, np.nan, 0

                            all_returns = []
                            if buy_count > 0:
                                all_returns.extend(buy_returns.tolist())
                            if sell_count > 0:
                                all_returns.extend(sell_returns.tolist())

                            if len(all_returns) > 0:
                                avg_return = np.mean(all_returns)
                                win_rate = (np.array(all_returns) > 0).mean() * 100
                                sharpe = np.mean(all_returns) / np.std(all_returns) if np.std(all_returns) > 0 else 0
                            else:
                                avg_return, win_rate, sharpe = np.nan, np.nan, np.nan

                            contract_results.append({
                                'Contract': contract_code,
                                'Contract_Name': contract_info['name'],
                                'COT_Lookback': cot_lb,
                                'Move_Period': move_pd,
                                'COT_Low': cot_low,
                                'COT_High': cot_high,
                                'Move_Low': move_low,
                                'Move_High': move_high,
                                'Signal_Logic': signal_name.replace('Signal_', ''),
                                'Forward_Period': period_name,
                                'Avg_Return': avg_return,
                                'Win_Rate': win_rate,
                                'Sharpe': sharpe,
                                'Buy_Avg': buy_avg,
                                'Buy_WinRate': buy_winrate,
                                'Buy_Count': buy_count,
                                'Sell_Avg': sell_avg,
                                'Sell_WinRate': sell_winrate,
                                'Sell_Count': sell_count,
                                'Total_Signals': buy_count + sell_count
                            })

    # Filter and summarize
    contract_results_df = pd.DataFrame(contract_results)
    contract_results_df = contract_results_df[contract_results_df['Total_Signals'] >= 10]

    if len(contract_results_df) > 0:
        all_results.append(contract_results_df)
        best = contract_results_df.nlargest(1, 'Sharpe').iloc[0]
        contract_summary.append({
            'Contract': contract_code,
            'Name': contract_info['name'],
            'Best_Sharpe': best['Sharpe'],
            'Best_AvgReturn': best['Avg_Return'],
            'Best_WinRate': best['Win_Rate'],
            'Best_Logic': best['Signal_Logic'],
            'Best_Period': best['Forward_Period'],
            'Best_Signals': best['Total_Signals']
        })
        print(f"   ✓ Best: {best['Signal_Logic']} | {best['Forward_Period']} | Sharpe: {best['Sharpe']:.3f} | Return: {best['Avg_Return']:+.2f}% | WinRate: {best['Win_Rate']:.1f}%")
        processed_count += 1
    else:
        print(f"   ✗ No valid configurations")
        skipped_count += 1

# Save results
print(f"\n{'='*80}")
print("SAVING RESULTS")
print(f"{'='*80}")

if len(all_results) > 0:
    full_results_df = pd.concat(all_results, ignore_index=True)
    full_results_df.to_csv('sandbox/cot_optimization_40_contracts_full.csv', index=False)
    print(f"✓ Full results: sandbox/cot_optimization_40_contracts_full.csv ({len(full_results_df)} rows)")

    summary_df = pd.DataFrame(contract_summary)
    summary_df = summary_df.sort_values('Best_Sharpe', ascending=False)
    summary_df.to_csv('sandbox/cot_optimization_40_contracts_summary.csv', index=False)
    print(f"✓ Summary: sandbox/cot_optimization_40_contracts_summary.csv ({len(summary_df)} contracts)")

    print(f"\n{'='*80}")
    print("TOP 15 CONTRACTS BY SHARPE RATIO")
    print(f"{'='*80}")
    for idx, row in summary_df.head(15).iterrows():
        print(f"{row['Contract']:5s} {row['Name']:20s} | Sharpe: {row['Best_Sharpe']:6.3f} | Return: {row['Best_AvgReturn']:+6.2f}% | WinRate: {row['Best_WinRate']:5.1f}% | {row['Best_Logic']:15s} | {row['Best_Period']}")

    print(f"\n{'='*80}")
    print(f"SUMMARY: Processed {processed_count} contracts, Skipped {skipped_count}")
    print(f"{'='*80}")
else:
    print("✗ No results to save")

print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("="*80)
