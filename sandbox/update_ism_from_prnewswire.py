"""
Update ISM data with correct values from PR Newswire press releases
Fixes corrupted data for September, October, November 2025
"""
import pandas as pd
from pathlib import Path

# Correct values from PR Newswire
# Manufacturing PMI - September, October, November 2025
mfg_corrections = {
    '2025-09-01': {
        'PMI': 49.1,
        'New_Orders': 48.9,
        'Production': 51.0,
        'Employment': 45.3,
        'Supplier_Deliveries': 52.6,
        'Inventories': 47.7,
        'Customers_Inventories': 43.7,
        'Prices': 61.9,
        'Backlog': 46.2,
        'New_Export_Orders': 43.0,
        'Imports': 44.7
    },
    '2025-10-01': {
        'PMI': 48.7,
        'New_Orders': 49.4,
        'Production': 48.2,
        'Employment': 46.0,
        'Supplier_Deliveries': 54.2,
        'Inventories': 45.8,
        'Customers_Inventories': 43.9,
        'Prices': 58.0,
        'Backlog': 47.9,
        'New_Export_Orders': 44.5,
        'Imports': 45.4
    },
    '2025-11-01': {
        'PMI': 48.2,
        'New_Orders': 47.4,
        'Production': 51.4,
        'Employment': 44.0,
        'Supplier_Deliveries': 49.3,
        'Inventories': 48.9,
        'Customers_Inventories': 44.7,
        'Prices': 58.5,
        'Backlog': 44.0,
        'New_Export_Orders': 46.2,
        'Imports': 48.9
    }
}

# Services PMI - September, October, November 2025
services_corrections = {
    '2025-09-01': {
        'PMI': 50.0,
        'Business_Activity': 49.9,
        'New_Orders': 50.4,
        'Employment': 47.2,
        'Supplier_Deliveries': 52.6,
        'Inventories': 47.8,
        'Prices': 69.4,
        'Backlog': 47.3,
        'New_Export_Orders': 46.5,
        'Imports': 49.2,
        'Inventory_Sentiment': 55.7
    },
    '2025-10-01': {
        'PMI': 52.4,
        'Business_Activity': 54.3,
        'New_Orders': 56.2,
        'Employment': 48.2,
        'Supplier_Deliveries': 50.8,
        'Inventories': 49.5,
        'Prices': 70.0,
        'Backlog': 40.8,
        'New_Export_Orders': 47.8,
        'Imports': 43.7,
        'Inventory_Sentiment': 55.5
    },
    '2025-11-01': {
        'PMI': 52.6,
        'Business_Activity': 54.5,
        'New_Orders': 52.9,
        'Employment': 48.9,
        'Supplier_Deliveries': 54.1,
        'Inventories': 53.4,
        'Prices': 65.4,
        'Backlog': 49.1,
        'New_Export_Orders': 48.7,
        'Imports': 48.9,
        'Inventory_Sentiment': 54.8
    }
}

print("=" * 80)
print("UPDATING ISM DATA WITH PR NEWSWIRE VALUES")
print("=" * 80)
print()

# Update Manufacturing data
print("Updating Manufacturing PMI data...")
mfg_file = 'data/economic/dbnomics_ism_manufacturing.csv'
df_mfg = pd.read_csv(mfg_file, index_col=0, parse_dates=True)

for date_str, values in mfg_corrections.items():
    date = pd.to_datetime(date_str)
    if date in df_mfg.index:
        print(f"  Updating {date.strftime('%Y-%m')}:")
        for col, new_val in values.items():
            old_val = df_mfg.loc[date, col]
            df_mfg.loc[date, col] = new_val
            print(f"    {col}: {old_val} → {new_val}")
    else:
        print(f"  ⚠ Date {date_str} not found in dataframe")

df_mfg.to_csv(mfg_file)
print(f"✓ Saved updated Manufacturing data to {mfg_file}")
print()

# Update Services data
print("Updating Services PMI data...")
services_file = 'data/economic/dbnomics_ism_services.csv'
df_services = pd.read_csv(services_file, index_col=0, parse_dates=True)

for date_str, values in services_corrections.items():
    date = pd.to_datetime(date_str)
    if date in df_services.index:
        print(f"  Updating {date.strftime('%Y-%m')}:")
        for col, new_val in values.items():
            old_val = df_services.loc[date, col]
            df_services.loc[date, col] = new_val
            print(f"    {col}: {old_val} → {new_val}")
    else:
        print(f"  ⚠ Date {date_str} not found in dataframe")

df_services.to_csv(services_file)
print(f"✓ Saved updated Services data to {services_file}")
print()

# Update quarterly files
print("Updating quarterly averages...")
mfg_q_file = 'data/economic/dbnomics_ism_manufacturing_quarterly.csv'
services_q_file = 'data/economic/dbnomics_ism_services_quarterly.csv'

df_mfg_q = df_mfg.resample('QE').mean()
df_services_q = df_services.resample('QE').mean()

df_mfg_q.to_csv(mfg_q_file)
df_services_q.to_csv(services_q_file)

print(f"✓ Saved updated Manufacturing quarterly to {mfg_q_file}")
print(f"✓ Saved updated Services quarterly to {services_q_file}")
print()

print("=" * 80)
print("UPDATE COMPLETE")
print("=" * 80)
print()
print("Updated months: September, October, November 2025")
print("Source: ISM press releases via PR Newswire")
print()
