# Global Liquidity Monitoring Dashboard - Technical Context

## Overview

Dashboard based on **Michael Howell's 3-layer Global Liquidity Index framework** (Capital Wars, 2020). Monitors US liquidity conditions through Central Bank policy, private credit transmission, and economic feedback loops.

**Location:** `src/analysis/liquidity_monitoring/`

---

## Two View Modes

### 1. Continuous (Z-Score) View - DEFAULT
- Each indicator's YoY change normalized by 5-year rolling Z-score
- Continuous range (-3 to +3 typical)
- Layer totals = **mean of Z-scores** across indicators
- Smoother, shows gradual changes

### 2. Discrete (Regime) View
- Traditional +1/0/-1 scoring per indicator
- Layer totals = sum of scores
- Used for regime classification

---

## Layer Weights (Composite Score)

| Layer | Weight | Description |
|-------|--------|-------------|
| L1 (CB) | 40% | Central Bank policy impulse |
| L2a (Private) | 35% | Credit transmission |
| L2b (Economic) | 25% | Economic feedback |

**Composite = L1×0.40 + L2a×0.35 + L2b×0.25**

---

## Layer 1: Central Bank Liquidity

**Single indicator: Net Liquidity**

### Net Liquidity Calculation
```
Net Liquidity = EMA(WALCL, 10) - EMA(TGA, 10) - EMA(RRP, 10)
```

- **Pre-2010:** `WALCL - TGA` only (RRP was not a policy tool)
- **Post-2010:** `WALCL - TGA - RRP`
- **10-period EMA** applied to raw weekly data before combining
- **Signal:** 12-month ROC, Z-score normalized

### Component Series (used for Net Liquidity calculation)

| ID | Name | FRED Code | Frequency |
|----|------|-----------|-----------|
| fed_balance_sheet | Fed Balance Sheet | WALCL | Weekly |
| tga | Treasury General Account | WTREGEN | Weekly |
| rrp | Reverse Repo Facility | RRPONTSYD | Daily |

### Unused Components (kept for reference)

| ID | Name | FRED Code | Notes |
|----|------|-----------|-------|
| fed_funds | Fed Funds Rate | DFF | For real rate calc |
| cpi | CPI All Items | CPIAUCSL | For real rate calc |
| dgs10 | 10-Year Treasury | DGS10 | For yield curve |
| dgs2 | 2-Year Treasury | DGS2 | For yield curve |

---

## Layer 2a: Private Credit / Wholesale Liquidity

**8 scored indicators** measuring credit transmission through private sector.

| ID | Name | FRED Code | Signal Type | Invert | Description |
|----|------|-----------|-------------|--------|-------------|
| bank_credit | Bank Credit Total | TOTLL | roc_12m | No | Total Loans & Leases (H.8) |
| ci_loans | C&I Loans | BUSLOANS | roc_12m | No | Commercial & Industrial Loans |
| m2 | M2 Money Supply | M2SL | roc_12m | No | M2 Money Stock |
| hy_spread | HY Credit Spread | BAMLH0A0HYM2 | level | Yes | ICE BofA US High Yield OAS |
| ig_spread | IG Credit Spread | BAMLC0A0CM | level | Yes | ICE BofA US Corporate OAS |
| nfci | Chicago Fed NFCI | NFCI | level | Yes | Negative = loose = bullish |
| mmf_assets | MMF Total Assets | WRMFNS | roc_12m | No | Retail Money Market Funds |
| sofr_effr_spread | SOFR-EFFR Spread | (derived) | level | Yes | Repo stress indicator |

### SOFR-EFFR Spread Calculation
```
Spread = (SOFR - EFFR) × 100  (in basis points)
```
- **<5bp:** Normal = Bullish
- **>15bp:** Stress = Bearish

### SOFR Data History (Combined Series)
| Period | Source | Notes |
|--------|--------|-------|
| 2000-2016 | USD LIBOR 3M | Calculated: TED Spread + T-Bill 3M |
| 2016-2018 | OBFR | Overnight Bank Funding Rate |
| 2018+ | SOFR | Secured Overnight Financing Rate |

### Removed Indicators
- **DXY (Dollar Index)** - removed per user request
- **VIX** - removed per user request

---

## Layer 2b: Economic Reality (COUNTERINTUITIVE Scoring)

**Key concept:** Weak economy = CB will ease = **bullish** for liquidity

| ID | Name | FRED Code | Signal Type | Invert | Description |
|----|------|-----------|-------------|--------|-------------|
| capacity_util | Capacity Utilization | TCU | level | Yes | <78% = slack = bullish |
| industrial_prod | Industrial Production | INDPRO | roc_12m | Yes | Weak growth = bullish |
| unemployment | Unemployment Rate | UNRATE | roc_29m | No | Rising = CB eases = bullish |
| cpi_level | CPI YoY | CPIAUCSL | yoy | Yes | Low inflation = bullish |
| cpi_momentum | CPI Momentum | CPIAUCSL | momentum | No | Deceleration = bullish |
| ppi_commodities | PPI All Commodities | PPIACO | level | Yes | Falling prices = bullish |

### CPI Momentum Calculation
```
Momentum = (3-month annualized) - (12-month change)
```
- **Negative:** Deceleration = CB can ease = Bullish
- **Positive:** Acceleration = CB tightens = Bearish

---

## Z-Score Calculation Details

### Frequency Auto-Detection
```python
avg_gap = (last_date - first_date).days / count
if avg_gap > 15:    # Monthly → 12 periods YoY, 60 window
elif avg_gap > 4:   # Weekly → 52 periods YoY, 260 window
else:               # Daily → 252 periods YoY, 1260 window
```

### Rolling Z-Score
```python
zscore = (value - rolling_mean) / rolling_std
# Window: 5 years (1260 daily, 260 weekly, 60 monthly)
# Min periods: window // 4
# Clipped to [-10, +10] to avoid extremes
```

### Layer Aggregation (Continuous View)
```python
layer_score = indicator_zscores.mean(axis=1, skipna=True)
```

---

## Data Sources

### FRED Series Used

| Code | Name | Frequency | Start |
|------|------|-----------|-------|
| WALCL | Fed Total Assets | Weekly | 2000 |
| WTREGEN | Treasury General Account | Weekly | 2000 |
| RRPONTSYD | Reverse Repo | Daily | 2000 |
| TOTLL | Bank Credit | Weekly | 2000 |
| BUSLOANS | C&I Loans | Monthly | 2000 |
| M2SL | M2 Money Supply | Monthly | 2000 |
| BAMLH0A0HYM2 | HY Spread | Daily | 2000 |
| BAMLC0A0CM | IG Spread | Daily | 2000 |
| NFCI | Financial Conditions | Weekly | 2000 |
| WRMFNS | MMF Assets | Weekly | 2000 |
| SOFR | Secured O/N Rate | Daily | 2018 |
| EFFR | Effective Fed Funds | Daily | 2000 |
| TCU | Capacity Utilization | Monthly | 2000 |
| INDPRO | Industrial Production | Monthly | 2000 |
| UNRATE | Unemployment Rate | Monthly | 2000 |
| CPIAUCSL | CPI All Items | Monthly | 2000 |
| PPIACO | PPI Commodities | Monthly | 2000 |

### Data Updates
- Cached in: `data/liquidity/us_liquidity_raw.csv`
- API key in: `data/fred_api_key.txt`

---

## File Structure

```
src/analysis/liquidity_monitoring/
├── streamlit_app.py          # Main app entry point
├── config/
│   └── indicators.py         # Indicator definitions & weights
├── calculations/
│   └── liquidity_indicators.py  # ROC, Z-score, scoring functions
│   └── regime_classifier.py     # Discrete regime classification
├── data/
│   └── loader.py             # FRED data fetching & caching
├── views/
│   ├── dashboard.py          # Main dashboard view
│   └── layer_detail.py       # Layer breakdown view
```

---

## Key Functions

### `calculate_net_liquidity(walcl, tga, rrp, smooth=True, ema_span=10)`
Computes Fed Net Liquidity with EMA smoothing, excluding RRP pre-2010.

### `calculate_continuous_indicator_score(series, config)`
Converts raw series to Z-score normalized measure, handling frequency detection and inversion.

### `calculate_historical_continuous_totals(raw_data, l1_config, l2a_config, l2b_config)`
Calculates historical layer scores as mean of Z-scores, forward-fills to align frequencies.

### `calculate_roc_12m(series)`
12-month rate of change with auto-frequency detection (12/52/252 periods).

---

## Interpretation Guide

### Z-Score Levels
| Z-Score | Interpretation |
|---------|----------------|
| > +2 | Extremely bullish |
| +1 to +2 | Bullish |
| -1 to +1 | Neutral |
| -2 to -1 | Bearish |
| < -2 | Extremely bearish |

### Composite Score
| Score | Bias |
|-------|------|
| > +0.5 | Bullish |
| -0.5 to +0.5 | Neutral |
| < -0.5 | Bearish |

---

## Version History

- **2026-03-13:** Initial Z-score continuous view implementation
- **2026-03-13:** L1 simplified to Net Liquidity only
- **2026-03-13:** Fixed pre-2010 jitter (excluded RRP, 10-period EMA)
- **2026-03-13:** Fixed WRMFSL → WRMFNS (MMF data update)
- **2026-03-13:** Extended SOFR history with USD LIBOR 3M (2000-2016)
- **2026-03-13:** Removed DXY and VIX from L2a
- **2026-03-13:** Fixed ROC frequency detection for monthly data
