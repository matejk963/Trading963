"""
CFTC Commitments of Traders (CoT) Legacy Report Fetcher

This module fetches historical legacy CoT reports from the CFTC website.
Legacy reports include:
- Futures Only format (fut_fin_txt)
- Futures and Options Combined format (com_fin_txt)
"""

import os
import requests
import zipfile
import io
from datetime import datetime
from typing import Optional, Literal
import pandas as pd


class CFTCLegacyFetcher:
    """Fetcher for CFTC Legacy CoT reports."""

    BASE_URL = "https://www.cftc.gov/files/dea/history"

    def __init__(self, data_dir: str = "data/cftc"):
        """
        Initialize the CFTC Legacy Fetcher.

        Args:
            data_dir: Directory to store downloaded data
        """
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def fetch_legacy_report(
        self,
        year: int,
        report_type: Literal["futures_only", "futures_and_options"] = "futures_only"
    ) -> Optional[str]:
        """
        Fetch legacy CoT report for a specific year.

        Args:
            year: Year to fetch (e.g., 2023)
            report_type: Type of report - "futures_only" or "futures_and_options"

        Returns:
            Path to the extracted file, or None if fetch failed
        """
        # Determine the file code based on report type
        # Updated URL structure as of 2024
        file_code = "fut_fin_txt" if report_type == "futures_only" else "com_fin_txt"

        # Construct URL
        url = f"{self.BASE_URL}/{file_code}_{year}.zip"

        print(f"Fetching {report_type} report for {year}...")
        print(f"URL: {url}")

        try:
            # Download the ZIP file
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Extract ZIP content
            zip_file = zipfile.ZipFile(io.BytesIO(response.content))

            # Extract all files to the data directory
            extract_path = os.path.join(self.data_dir, f"{file_code}_{year}")
            os.makedirs(extract_path, exist_ok=True)

            zip_file.extractall(extract_path)

            # Get the extracted file path
            extracted_files = zip_file.namelist()
            print(f"Successfully downloaded and extracted {len(extracted_files)} file(s)")
            print(f"Extracted to: {extract_path}")

            # Return the path to the main data file (usually a .txt file)
            txt_files = [f for f in extracted_files if f.endswith('.txt')]
            if txt_files:
                return os.path.join(extract_path, txt_files[0])

            return extract_path

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            return None
        except zipfile.BadZipFile as e:
            print(f"Error extracting ZIP file: {e}")
            return None

    def fetch_current_year(
        self,
        report_type: Literal["futures_only", "futures_and_options"] = "futures_only"
    ) -> Optional[str]:
        """
        Fetch the current year's legacy CoT report.

        Args:
            report_type: Type of report - "futures_only" or "futures_and_options"

        Returns:
            Path to the extracted file, or None if fetch failed
        """
        current_year = datetime.now().year

        # Current year uses the same format as historical years
        return self.fetch_legacy_report(current_year, report_type)

    def fetch_year_range(
        self,
        start_year: int,
        end_year: int,
        report_type: Literal["futures_only", "futures_and_options"] = "futures_only"
    ) -> list[str]:
        """
        Fetch legacy CoT reports for a range of years.

        Args:
            start_year: Starting year (inclusive)
            end_year: Ending year (inclusive)
            report_type: Type of report - "futures_only" or "futures_and_options"

        Returns:
            List of paths to extracted files
        """
        paths = []

        for year in range(start_year, end_year + 1):
            path = self.fetch_legacy_report(year, report_type)
            if path:
                paths.append(path)

        return paths

    def load_legacy_data(self, file_path: str) -> Optional[pd.DataFrame]:
        """
        Load legacy CoT data from a text file into a pandas DataFrame.

        Args:
            file_path: Path to the legacy CoT text file

        Returns:
            DataFrame with the CoT data, or None if loading failed
        """
        try:
            # Legacy files are typically pipe-delimited or comma-delimited
            # Try to detect the delimiter
            with open(file_path, 'r') as f:
                first_line = f.readline()

            delimiter = ',' if ',' in first_line else None

            # Read the data
            df = pd.read_csv(file_path, delimiter=delimiter, low_memory=False)

            print(f"Loaded {len(df)} rows and {len(df.columns)} columns")
            print(f"Columns: {list(df.columns)}")

            return df

        except Exception as e:
            print(f"Error loading data from {file_path}: {e}")
            return None


def main():
    """Example usage of the CFTC Legacy Fetcher."""

    # Initialize fetcher
    fetcher = CFTCLegacyFetcher()

    # Fetch a specific year
    print("=" * 80)
    print("Fetching 2023 Futures Only Report")
    print("=" * 80)
    file_path = fetcher.fetch_legacy_report(2023, "futures_only")

    if file_path:
        print(f"\nData saved to: {file_path}")

        # Load and display sample data
        df = fetcher.load_legacy_data(file_path)
        if df is not None:
            print("\nFirst few rows:")
            print(df.head())
            print("\nData shape:", df.shape)

    # Fetch current year
    print("\n" + "=" * 80)
    print("Fetching Current Year Report")
    print("=" * 80)
    current_path = fetcher.fetch_current_year("futures_only")

    if current_path:
        print(f"\nCurrent year data saved to: {current_path}")


if __name__ == "__main__":
    main()
