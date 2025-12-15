"""
COT Database Updater
Updates the main COT database with the latest legacy format data from CFTC
"""
import os
import pandas as pd
import requests
import zipfile
import io
from datetime import datetime
from typing import Tuple, Optional


class COTDatabaseUpdater:
    """Updates COT database with latest legacy format data"""

    BASE_URL = "https://www.cftc.gov/files/dea/history"

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.data_dir = os.path.join(project_root, 'data', 'cftc')
        self.main_db_file = os.path.join(self.data_dir, 'legacy_long_format_combined_2005_2025.csv')

    def get_current_status(self) -> dict:
        """Get current database status"""
        if not os.path.exists(self.main_db_file):
            return {
                'exists': False,
                'records': 0,
                'latest_date': None,
                'days_behind': None
            }

        df = pd.read_csv(self.main_db_file, low_memory=False)
        df['date'] = pd.to_datetime(df['As_of_Date_in_Form_YYYY-MM-DD'], errors='coerce')
        df = df[df['date'].notna()]

        latest_date = df['date'].max()
        today = datetime.now()
        days_behind = (today - latest_date).days

        return {
            'exists': True,
            'records': len(df),
            'latest_date': latest_date,
            'days_behind': days_behind
        }

    def download_latest_data(self) -> Tuple[Optional[pd.DataFrame], str]:
        """
        Download latest legacy format data from CFTC

        Returns:
            Tuple of (DataFrame, status_message)
        """
        current_year = datetime.now().year

        # TRUE legacy format URL (not disaggregated)
        url = f"{self.BASE_URL}/deacot{current_year}.zip"

        try:
            # Download the ZIP file
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Extract ZIP content
            zip_file = zipfile.ZipFile(io.BytesIO(response.content))

            # Find the .txt file
            txt_files = [f for f in zip_file.namelist() if f.endswith('.txt')]
            if not txt_files:
                return None, f"No .txt file found in {url}"

            # Read the data directly from ZIP
            with zip_file.open(txt_files[0]) as f:
                df = pd.read_csv(f, low_memory=False)

            # Standardize column names (spaces to underscores)
            df.columns = df.columns.str.replace(' ', '_')

            # Create unified date column
            if 'As_of_Date_in_Form_YYYY-MM-DD' not in df.columns:
                return None, "Missing expected date column"

            df['date'] = pd.to_datetime(df['As_of_Date_in_Form_YYYY-MM-DD'], errors='coerce')
            df = df[df['date'].notna()]

            date_range = f"{df['date'].min().strftime('%Y-%m-%d')} to {df['date'].max().strftime('%Y-%m-%d')}"
            msg = f"Downloaded {len(df):,} records ({date_range})"

            return df, msg

        except requests.exceptions.RequestException as e:
            return None, f"Download failed: {str(e)}"
        except Exception as e:
            return None, f"Error processing data: {str(e)}"

    def update_database(self) -> Tuple[bool, str]:
        """
        Update the database with latest data

        Returns:
            Tuple of (success, message)
        """
        # Check current status
        status = self.get_current_status()
        if not status['exists']:
            return False, f"Main database not found: {self.main_db_file}"

        # Download latest data
        df_new, download_msg = self.download_latest_data()
        if df_new is None:
            return False, download_msg

        # Load current database
        df_current = pd.read_csv(self.main_db_file, low_memory=False)
        df_current['date'] = pd.to_datetime(df_current['As_of_Date_in_Form_YYYY-MM-DD'], errors='coerce')
        df_current = df_current[df_current['date'].notna()]

        current_year = datetime.now().year

        # Remove existing current year data from database
        df_current_filtered = df_current[df_current['date'].dt.year < current_year].copy()
        records_removed = len(df_current) - len(df_current_filtered)

        # Prepare new data for integration
        df_new_clean = df_new.drop('date', axis=1)
        df_current_clean = df_current_filtered.drop('date', axis=1)

        # Combine
        df_combined = pd.concat([df_current_clean, df_new_clean], ignore_index=True)

        # Sort by date
        df_combined['sort_date'] = pd.to_datetime(df_combined['As_of_Date_in_Form_YYYY-MM-DD'], errors='coerce')
        df_combined = df_combined.sort_values(['sort_date', 'Market_and_Exchange_Names'])
        df_combined = df_combined.drop('sort_date', axis=1)

        net_change = len(df_combined) - len(df_current)

        # Create backup
        backup_file = self.main_db_file + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        df_current.to_csv(backup_file, index=False)

        # Save updated file
        df_combined.to_csv(self.main_db_file, index=False)

        # Verify
        df_verify = pd.read_csv(self.main_db_file, low_memory=False)
        df_verify['date'] = pd.to_datetime(df_verify['As_of_Date_in_Form_YYYY-MM-DD'], errors='coerce')
        df_verify = df_verify[df_verify['date'].notna()]
        latest_date = df_verify['date'].max()

        message = f"""Update complete:
- Removed {records_removed:,} old {current_year} records
- Added {len(df_new):,} new records
- Net change: {net_change:+,} records
- Total records: {len(df_combined):,}
- Latest data: {latest_date.strftime('%Y-%m-%d')}
- Backup: {os.path.basename(backup_file)}"""

        return True, message
