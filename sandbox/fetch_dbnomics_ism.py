"""
Fetch ISM Manufacturing and Non-Manufacturing PMI from DBnomics - All Available History
"""
import pandas as pd
import requests
from pathlib import Path

# ISM Manufacturing datasets from DBnomics
ISM_MFG_DATASETS = {
    'PMI': 'pmi',                          # Manufacturing PMI
    'New_Orders': 'neword',                # New Orders
    'Production': 'production',            # Production
    'Employment': 'employment',            # Employment
    'Supplier_Deliveries': 'supdel',       # Supplier Deliveries
    'Inventories': 'inventories',          # Inventories
    'Customers_Inventories': 'cusinv',     # Customers' Inventories
    'Prices': 'prices',                    # Prices
    'Backlog': 'bacord',                   # Backlog of Orders
    'New_Export_Orders': 'newexpord',      # New Export Orders
    'Imports': 'imports',                  # Imports
}

# ISM Non-Manufacturing (Services) datasets from DBnomics
ISM_SERVICES_DATASETS = {
    'PMI': 'nm-pmi',                       # Non-Manufacturing PMI
    'Business_Activity': 'nm-busact',      # Business Activity
    'New_Orders': 'nm-neword',             # New Orders
    'Employment': 'nm-employment',         # Employment
    'Supplier_Deliveries': 'nm-supdel',    # Supplier Deliveries
    'Inventories': 'nm-inventories',       # Inventories
    'Prices': 'nm-prices',                 # Prices
    'Backlog': 'nm-bacord',                # Backlog of Orders
    'New_Export_Orders': 'nm-newexpord',   # New Export Orders
    'Imports': 'nm-imports',               # Imports
    'Inventory_Sentiment': 'nm-invsen',    # Inventory Sentiment
}


def fetch_series_data(provider, dataset_code, series_code='in'):
    """
    Fetch a single series from DBnomics API

    Args:
        provider: Provider code (e.g., 'ISM')
        dataset_code: Dataset code (e.g., 'pmi')
        series_code: Series code (default 'in' for Index)

    Returns:
        pandas Series with the data
    """
    url = f"https://api.db.nomics.world/v22/series/{provider}/{dataset_code}/{series_code}?observations=1"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        if 'series' not in data or 'docs' not in data['series'] or not data['series']['docs']:
            return None

        # Get the first (and only) doc
        doc = data['series']['docs'][0]

        # Extract period and value arrays
        periods = doc.get('period', [])
        values = doc.get('value', [])

        if not periods or not values:
            return None

        # Convert to pandas Series
        series = pd.Series(values, index=pd.to_datetime(periods))
        series = series.sort_index()

        return series

    except Exception as e:
        print(f"  Error fetching {dataset_code}/{series_code}: {e}")
        return None


def fetch_ism_data():
    """Fetch ISM Manufacturing and Services PMI with all sub-indices from DBnomics"""

    print("=" * 90)
    print("FETCHING ISM PMI DATA FROM DBNOMICS")
    print("=" * 90)
    print()
    print(f"Fetching ISM Manufacturing: {len(ISM_MFG_DATASETS)} indicators")
    print(f"Fetching ISM Services: {len(ISM_SERVICES_DATASETS)} indicators")
    print(f"Frequency: Monthly")
    print(f"Note: Values above 50 indicate expansion, below 50 indicate contraction")
    print()

    # Fetch Manufacturing data
    print("Fetching Manufacturing indicators...")
    mfg_data = {}
    mfg_failed = []

    for name, dataset_code in ISM_MFG_DATASETS.items():
        # PMI dataset uses 'pm' series code, others use 'in'
        series_code = 'pm' if dataset_code == 'pmi' else 'in'
        series = fetch_series_data('ISM', dataset_code, series_code)
        if series is not None and len(series) > 0:
            mfg_data[name] = series
            print(f"  ✓ {name}: {dataset_code} ({len(series)} months)")
        else:
            mfg_failed.append(f"{name} ({dataset_code})")
            print(f"  ✗ {name}: {dataset_code} - NO DATA")

    print()

    # Fetch Services data
    print("Fetching Services indicators...")
    services_data = {}
    services_failed = []

    for name, dataset_code in ISM_SERVICES_DATASETS.items():
        # PMI dataset uses 'pm' series code, others use 'in'
        series_code = 'pm' if dataset_code == 'nm-pmi' else 'in'
        series = fetch_series_data('ISM', dataset_code, series_code)
        if series is not None and len(series) > 0:
            services_data[name] = series
            print(f"  ✓ {name}: {dataset_code} ({len(series)} months)")
        else:
            services_failed.append(f"{name} ({dataset_code})")
            print(f"  ✗ {name}: {dataset_code} - NO DATA")

    print()

    if mfg_failed:
        print(f"Manufacturing series not available: {', '.join(mfg_failed)}")
        print()

    if services_failed:
        print(f"Services series not available: {', '.join(services_failed)}")
        print()

    # Create dataframes
    df_mfg = pd.DataFrame(mfg_data)
    df_services = pd.DataFrame(services_data)

    print(f"✓ Manufacturing data: {len(df_mfg)} months from {df_mfg.index.min().strftime('%Y-%m-%d')} to {df_mfg.index.max().strftime('%Y-%m-%d')}")
    print(f"✓ Services data: {len(df_services)} months from {df_services.index.min().strftime('%Y-%m-%d')} to {df_services.index.max().strftime('%Y-%m-%d')}")
    print()

    print("=" * 90)
    print("ISM MANUFACTURING PMI - LAST 24 MONTHS")
    print("=" * 90)
    print()

    pd.set_option('display.float_format', lambda x: f'{x:.1f}')
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 150)

    print(df_mfg.tail(24).to_string())
    print()

    print("=" * 90)
    print("ISM SERVICES PMI - LAST 24 MONTHS")
    print("=" * 90)
    print()

    print(df_services.tail(24).to_string())
    print()

    # Summary statistics
    print("=" * 90)
    print("LATEST VALUES (Most Recent Month)")
    print("=" * 90)
    print()

    print(f"Latest Month: {df_mfg.index[-1].strftime('%B %Y')}")
    print()

    print("MANUFACTURING:")
    for col in df_mfg.columns:
        value = df_mfg[col].iloc[-1]
        status = "🟢 EXPANSION" if value > 50 else "🔴 CONTRACTION"
        print(f"  {col:25s}: {value:5.1f} {status}")

    print()
    print("SERVICES:")
    for col in df_services.columns:
        value = df_services[col].iloc[-1]
        status = "🟢 EXPANSION" if value > 50 else "🔴 CONTRACTION"
        print(f"  {col:25s}: {value:5.1f} {status}")

    print()

    # Calculate quarterly averages
    print("=" * 90)
    print("QUARTERLY AVERAGES - LAST 10 QUARTERS")
    print("=" * 90)
    print()

    df_mfg_q = df_mfg.resample('QE').mean().tail(10)
    df_services_q = df_services.resample('QE').mean().tail(10)

    print("MANUFACTURING PMI (Quarterly):")
    if 'PMI' in df_mfg_q.columns and 'New_Orders' in df_mfg_q.columns:
        cols_to_show = [c for c in ['PMI', 'New_Orders', 'Production', 'Employment', 'Prices'] if c in df_mfg_q.columns]
        print(df_mfg_q[cols_to_show].to_string())
    print()

    print("SERVICES PMI (Quarterly):")
    if 'PMI' in df_services_q.columns:
        cols_to_show = [c for c in ['PMI', 'Business_Activity', 'New_Orders', 'Employment', 'Prices'] if c in df_services_q.columns]
        print(df_services_q[cols_to_show].to_string())
    print()

    # Save to CSV - save FULL history
    import os
    os.makedirs('data/economic', exist_ok=True)

    mfg_file = 'data/economic/dbnomics_ism_manufacturing.csv'
    services_file = 'data/economic/dbnomics_ism_services.csv'
    mfg_q_file = 'data/economic/dbnomics_ism_manufacturing_quarterly.csv'
    services_q_file = 'data/economic/dbnomics_ism_services_quarterly.csv'

    # Save full history
    df_mfg.to_csv(mfg_file)
    df_services.to_csv(services_file)

    # Calculate quarterly averages on full history
    df_mfg_q_full = df_mfg.resample('QE').mean()
    df_services_q_full = df_services.resample('QE').mean()

    df_mfg_q_full.to_csv(mfg_q_file)
    df_services_q_full.to_csv(services_q_file)

    print(f"✓ Saved Manufacturing data to: {mfg_file} ({len(df_mfg)} months)")
    print(f"✓ Saved Services data to: {services_file} ({len(df_services)} months)")
    print(f"✓ Saved Manufacturing quarterly to: {mfg_q_file} ({len(df_mfg_q_full)} quarters)")
    print(f"✓ Saved Services quarterly to: {services_q_file} ({len(df_services_q_full)} quarters)")
    print()

    return df_mfg, df_services, df_mfg_q_full, df_services_q_full


if __name__ == '__main__':
    fetch_ism_data()
