"""
ISM PMI/NMI Data Updater
Fetches latest ISM reports from official website (primary) or PR Newswire (fallback)
"""
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import os
import re


def fetch_from_ism_official(report_type='manufacturing', target_month=None):
    """
    Fetch latest ISM report from official ISM website

    Args:
        report_type: 'manufacturing' or 'services'
        target_month: datetime object for the month to fetch (default: latest available)

    Returns:
        dict with {date, all_indicators, source} or None if failed
    """
    try:
        # ISM official URLs - updated pattern
        # Try latest month first, then specific month if provided
        month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                      'july', 'august', 'september', 'october', 'november', 'december']

        if target_month:
            month_name = month_names[target_month.month - 1]
        else:
            # Try to guess latest month (current month - 1)
            from datetime import datetime
            last_month = datetime.now().month - 1
            if last_month == 0:
                last_month = 12
            month_name = month_names[last_month - 1]

        if report_type == 'manufacturing':
            url = f'https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/{month_name}/'
        else:  # services
            url = f'https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/services/{month_name}/'

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        full_text = soup.get_text()

        # Extract report date from header (most reliable)
        # Look for h1 or h3 with pattern "Month YYYY ISM Report" or "Month YYYY"
        date_found = False
        for header in soup.find_all(['h1', 'h2', 'h3']):
            header_text = header.get_text().strip()
            # Pattern: "December 2025 ISM® Manufacturing PMI® Report"
            match = re.search(r'([A-Z][a-z]+)\s+(\d{4})\s+ISM', header_text)
            if match:
                month_str, year_str = match.groups()
                report_date = pd.to_datetime(f"{month_str} 1, {year_str}")
                date_found = True
                break

            # Alternative pattern: "MANUFACTURING AT A GLANCE December 2025"
            match = re.search(r'([A-Z][a-z]+)\s+(\d{4})$', header_text)
            if match:
                month_str, year_str = match.groups()
                report_date = pd.to_datetime(f"{month_str} 1, {year_str}")
                date_found = True
                break

        if not date_found:
            return None

        # Extract all indicators with regex patterns
        all_indicators = {}

        # Define patterns for each indicator
        # Each tuple: (growth_pattern, contraction_pattern, indicator_name)
        pmi_patterns = [
            # PMI overall
            (r'The (?:\w+) manufacturing industries? reporting growth[^:]*:\s*([^.]+?)\.',
             r'The (?:\w+) industries? reporting contraction[^:]*:\s*([^.]+?)\.',
             'PMI'),

            # New Orders
            (r'industries? that reported growth in new orders[^:]*:\s*([^.]+?)\.',
             r'industries? reporting a decrease in new orders[^:]*:\s*([^.]+?)\.',
             'New_Orders'),

            # Production
            (r'industries? reporting growth in production[^:]*:\s*([^.]+?)\.',
             r'industries? reporting a decrease in production[^:]*:\s*([^.]+?)\.',
             'Production'),

            # Employment
            (r'industries? reporting employment growth[^:]*:\s*([^.]+?)\.',
             r'industries? reporting a decrease in employment[^:]*:\s*([^.]+?)\.',
             'Employment'),

            # Supplier Deliveries
            (r'industries? reporting slower (?:supplier )?deliveries[^:]*:\s*([^.]+?)\.',
             r'industries? reporting faster deliveries[^:]*:\s*([^.]+?)\.',
             'Supplier_Deliveries'),

            # Inventories
            (r'industries? reporting higher inventories[^:]*:\s*([^.]+?)\.',
             r'industries? reporting lower inventories[^:]*:\s*([^.]+?)\.',
             'Inventories'),

            # Prices
            (r'industries? that reported paying increased prices[^:]*:\s*([^.]+?)\.',
             r'industries? that reported paying decreased prices[^:]*:\s*([^.]+?)\.',
             'Prices'),

            # Backlog
            (r'industries? reporting (?:higher|increased) backlogs?[^:]*:\s*([^.]+?)\.',
             r'industries? reporting (?:lower|decreased) backlogs?[^:]*:\s*([^.]+?)\.',
             'Backlog'),

            # New Export Orders
            (r'(?:that )?reported growth in new export orders[^:]*:\s*([^.]+?)\.',
             r'(?:that )?reported a decrease in new export orders[^:]*:\s*([^.]+?)\.',
             'New_Export_Orders'),

            # Imports
            (r'industries? (?:that )?reported higher (?:import )?(?:volumes|imports)[^:]*:\s*([^.]+?)\.',
             r'industries? that reported lower (?:import )?volumes[^:]*:\s*([^.]+?)\.',
             'Imports'),
        ]

        # Extract each indicator
        for growth_pattern, contraction_pattern, indicator_name in pmi_patterns:
            growth_match = re.search(growth_pattern, full_text, re.IGNORECASE | re.DOTALL)
            contraction_match = re.search(contraction_pattern, full_text, re.IGNORECASE | re.DOTALL)

            growing_sectors = []
            contracting_sectors = []

            if growth_match:
                sectors_text = growth_match.group(1)
                # Split by semicolon and "and", clean up
                sectors = [s.strip() for s in re.split(r';|(?:\s+and\s+)', sectors_text) if s.strip()]
                growing_sectors = [s.replace('and ', '', 1).strip() if s.startswith('and ') else s
                                 for s in sectors if len(s.strip()) > 3]
                # Normalize: remove commas from sector names
                growing_sectors = [s.replace(',', '') for s in growing_sectors]

            if contraction_match:
                sectors_text = contraction_match.group(1)
                sectors = [s.strip() for s in re.split(r';|(?:\s+and\s+)', sectors_text) if s.strip()]
                contracting_sectors = [s.replace('and ', '', 1).strip() if s.startswith('and ') else s
                                     for s in sectors if len(s.strip()) > 3]
                # Normalize: remove commas from sector names
                contracting_sectors = [s.replace(',', '') for s in contracting_sectors]

            if growing_sectors or contracting_sectors:
                all_indicators[indicator_name] = {
                    'growing': growing_sectors,
                    'contracting': contracting_sectors
                }

        if not all_indicators:
            return None

        return {
            'date': report_date,
            'all_indicators': all_indicators,
            'source': 'ISM Official'
        }

    except Exception as e:
        print(f"Error fetching from ISM official: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_from_prnewswire(report_type='manufacturing', target_month=None):
    """
    Fetch ISM report from PR Newswire (fallback)
    Tries direct URL patterns since PR Newswire search requires JavaScript

    Args:
        report_type: 'manufacturing' or 'services'
        target_month: datetime object for the month to fetch (default: current month)

    Returns:
        dict with {date, growing_sectors, contracting_sectors} or None if failed
    """
    try:
        if target_month is None:
            target_month = datetime.now()

        month_name = target_month.strftime('%B')
        month_lower = month_name.lower()
        year = target_month.year

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        # Try PR Newswire's company page for ISM which lists all their press releases
        article_url = None
        ism_company_url = "https://www.prnewswire.com/news/institute-for-supply-management"

        try:
            response = requests.get(ism_company_url, headers=headers, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # Look for article cards or links containing the report
                # Try multiple selectors
                potential_links = []

                # Method 1: Find all anchor tags
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '')
                    link_text = link.get_text().strip().lower()

                    # Check if this is the right article
                    if '/news-releases/' in href and 'pmi' in (href.lower() + link_text):
                        # Check month and year match
                        if month_lower in (href.lower() + link_text) and str(year) in (href.lower() + link_text):
                            # Check report type
                            if report_type == 'manufacturing' and 'manufacturing' in (href.lower() + link_text):
                                potential_links.append((href, link_text))
                            elif report_type == 'services' and 'service' in (href.lower() + link_text):
                                potential_links.append((href, link_text))

                if potential_links:
                    # Take the first match
                    href, text = potential_links[0]
                    article_url = 'https://www.prnewswire.com' + href if href.startswith('/') else href
                    print(f"Found article via ISM company page: {text[:50]}")
                else:
                    print(f"No matching articles found on ISM company page for {month_name} {year}")

        except Exception as e:
            print(f"ISM company page search failed: {e}")
            import traceback
            traceback.print_exc()

        if not article_url:
            print(f"Could not find PR Newswire article URL for {month_name} {year}")
            return None

        print(f"Fetching article: {article_url}")

        # Fetch and parse the article
        article_response = requests.get(article_url, headers=headers, timeout=10)
        if article_response.status_code != 200:
            return None

        article_soup = BeautifulSoup(article_response.text, 'html.parser')
        article_text = article_soup.get_text()

        # Extract date from article
        date = pd.to_datetime(f"{month_name} 1, {year}")

        # Extract sector rankings with precise patterns
        # Pattern: industries reporting growth...are: Sector1; Sector2; Sector3; and SectorN.
        growing_pattern = r'industries? reporting growth[^:]*:\s*([^.]+)\.\s*The'
        contracting_pattern = r'industries? reporting contraction[^:]*:\s*([^.]+)\.'

        growing_match = re.search(growing_pattern, article_text, re.DOTALL | re.IGNORECASE)
        contracting_match = re.search(contracting_pattern, article_text, re.DOTALL | re.IGNORECASE)

        growing_sectors = []
        contracting_sectors = []

        if growing_match:
            growing_text = growing_match.group(1)
            # Split by semicolon (ISM uses semicolons to separate sectors)
            sectors = re.split(r';', growing_text)
            for sector in sectors:
                # Clean up: remove "and" at start, strip whitespace
                sector = sector.strip()
                if sector.startswith('and '):
                    sector = sector[4:].strip()
                if len(sector) > 3 and not sector.lower().startswith('the '):
                    growing_sectors.append(sector)

        if contracting_match:
            contracting_text = contracting_match.group(1)
            sectors = re.split(r';', contracting_text)
            for sector in sectors:
                sector = sector.strip()
                if sector.startswith('and '):
                    sector = sector[4:].strip()
                if len(sector) > 3 and not sector.lower().startswith('the '):
                    contracting_sectors.append(sector)

        if growing_sectors or contracting_sectors:
            return {
                'date': date,
                'growing_sectors': growing_sectors,
                'contracting_sectors': contracting_sectors,
                'source': 'PR Newswire'
            }

        return None

    except Exception as e:
        print(f"Error fetching from PR Newswire: {e}")
        import traceback
        traceback.print_exc()
        return None


def add_neutral_sectors(growing, contracting, all_sectors, date, indicator):
    """
    Add unreported (neutral) sectors with middle rankings

    Args:
        growing: list of growing sectors
        contracting: list of contracting sectors
        all_sectors: list of all possible sectors
        date: report date
        indicator: indicator name

    Returns:
        list of [date, indicator, sector, rank] rows
    """
    rows = []
    rank = 1

    # Growing sectors
    for sector in growing:
        rows.append([date, indicator, sector, rank])
        rank += 1

    # Neutral/unreported sectors
    reported_sectors = set(growing + contracting)
    unreported_sectors = sorted(set(all_sectors) - reported_sectors)

    for sector in unreported_sectors:
        rows.append([date, indicator, sector, rank])
        rank += 1

    # Contracting sectors
    for sector in contracting:
        rows.append([date, indicator, sector, rank])
        rank += 1

    return rows


def update_ism_data(report_type='manufacturing', data_dir=None):
    """
    Main update function - tries ISM official first, falls back to PR Newswire

    Args:
        report_type: 'manufacturing' or 'services'
        data_dir: path to data directory (default: PROJECT_ROOT/data/economic)

    Returns:
        dict with status and message
    """
    if data_dir is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        data_dir = os.path.join(project_root, 'data', 'economic')

    # Load existing data
    if report_type == 'manufacturing':
        csv_file = os.path.join(data_dir, 'ism_manufacturing_sector_rankings.csv')
    else:
        csv_file = os.path.join(data_dir, 'ism_services_sector_rankings.csv')

    if not os.path.exists(csv_file):
        return {'success': False, 'message': f'Data file not found: {csv_file}'}

    df = pd.read_csv(csv_file, parse_dates=['Date'])
    latest_date = df['Date'].max()
    all_sectors = sorted(df['Sector'].unique())

    # Check if we need to fetch next month
    next_month = latest_date + pd.DateOffset(months=1)
    current_time = datetime.now()

    # Don't try to fetch if next month is in the future
    if next_month.year > current_time.year or (next_month.year == current_time.year and next_month.month > current_time.month):
        return {'success': False, 'message': f'Data is up to date (latest: {latest_date.strftime("%B %Y")})'}

    # Try ISM official first
    print(f"Fetching {report_type} data from ISM official website...")
    data = fetch_from_ism_official(report_type, next_month)

    # Fall back to PR Newswire
    if data is None:
        print(f"ISM official failed, trying PR Newswire...")
        data = fetch_from_prnewswire(report_type, next_month)

    if data is None:
        return {'success': False, 'message': 'Could not fetch data from ISM or PR Newswire'}

    # Check if this month already exists
    if data['date'] in df['Date'].values:
        return {'success': False, 'message': f'Data for {data["date"].strftime("%B %Y")} already exists'}

    # Process and add data for all indicators
    new_rows = []
    total_growing = 0
    total_contracting = 0

    if 'all_indicators' in data:
        # New format from updated ISM scraper
        for indicator_name, indicator_data in data['all_indicators'].items():
            growing = indicator_data['growing']
            contracting = indicator_data['contracting']

            total_growing += len(growing)
            total_contracting += len(contracting)

            rows = add_neutral_sectors(growing, contracting, all_sectors, data['date'], indicator_name)
            new_rows.extend(rows)
    else:
        # Old format fallback (PR Newswire)
        growing = data.get('growing_sectors', [])
        contracting = data.get('contracting_sectors', [])
        total_growing = len(growing)
        total_contracting = len(contracting)

        # Only add PMI for now
        rows = add_neutral_sectors(growing, contracting, all_sectors, data['date'], 'PMI')
        new_rows.extend(rows)

    if not new_rows:
        return {'success': False, 'message': 'No sector rankings found in report'}

    new_df = pd.DataFrame(new_rows, columns=['Date', 'Indicator', 'Sector', 'Rank'])
    updated_df = pd.concat([df, new_df], ignore_index=True).sort_values(['Date', 'Indicator', 'Rank'])

    # Save
    updated_df.to_csv(csv_file, index=False)

    indicators_count = len(data.get('all_indicators', {'PMI': {}}))

    return {
        'success': True,
        'message': f'Added {data["date"].strftime("%B %Y")} data from {data["source"]}',
        'date': data['date'],
        'source': data['source'],
        'growing_count': total_growing,
        'contracting_count': total_contracting,
        'indicators_count': indicators_count
    }


if __name__ == '__main__':
    # Test
    result = update_ism_data('manufacturing')
    print(result)
