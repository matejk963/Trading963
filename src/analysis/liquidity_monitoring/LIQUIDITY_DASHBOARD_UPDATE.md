# Global Liquidity Monitoring Dashboard - Technical Context

## Overview

Dashboard based on **Michael Howell's 3-layer Global Liquidity Index framework** (Capital Wars, 2020)
combined with **Mark Boucher's Austrian Liquidity Cycle** (The Hedge Fund Edge, 1999).
Monitors US liquidity conditions through Central Bank policy, private credit transmission,
and economic feedback loops.

**Location:** `src/analysis/liquidity_monitoring/`

---

## Three View Modes

### 1. Continuous (Z-Score) View — DEFAULT
- Each indicator's YoY change normalized by 5-year rolling Z-score
- Continuous range (-3 to +3 typical)
- Layer totals = **mean of Z-scores** across indicators
- Smoother, shows gradual changes

### 2. Discrete (Regime) View
- Traditional +1/0/-1 scoring per indicator
- Layer totals = sum of scores
- Used for regime classification

### 3. Transmission Chain View ← NEW
- Visualises liquidity flow through 7 sequential stages from CB impulse to real economy
- Each stage shows its indicators, their current signal, and whether transmission is flowing or breaking
- Composite "how far has the impulse traveled" reading
- Break detection: identifies at which stage transmission is failing
- See **Section: Transmission Chain View** for full specification

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

**Two indicators: Net Liquidity + Real Policy Rate**

### Design Decisions
- **Yield curve removed from L1.** The yield curve is substantially endogenous to liquidity
  conditions — it is downstream of what L1 measures, not an input. It belongs in L2a as a
  transmission signal (bank NIM incentive), not as a CB impulse indicator.
- **Two independent CB dimensions retained:**
  1. Quantity of money injected (Net Liquidity)
  2. Price of money (Real Policy Rate)

---

### Indicator 1: Net Liquidity

#### Calculation
```
Net Liquidity = EMA(WALCL, 10) - EMA(TGA, 10) - EMA(RRP, 10)
```

- **Pre-2010:** `WALCL - TGA` only — RRP was not a policy tool before 2013
- **Post-2010:** `WALCL - TGA - RRP`
- **10-period EMA** applied to raw weekly data before combining
- **Signal:** 12-month ROC, Z-score normalized

#### Why Subtract TGA and RRP
The TGA (Treasury's account at the Fed) and RRP (money market funds parking cash
at the Fed overnight) both remove reserves from the banking system's usable pool.
A growing Fed balance sheet with a simultaneously surging TGA can be net tightening.
RRP absorption means liquidity abundance is not transmitting into private markets.
Net liquidity = what banks actually have available to deploy.

**Important nuance:** When QT causes Treasuries to re-enter private hands, those
securities *increase* private collateral availability (L2a positive) even as the
balance sheet shrinks (L1 negative). QT therefore has a split signal across layers —
this is by design, not a bug. The layer interaction matrix handles it.

#### Zero Lower Bound Flag
When DFF ≤ 0.25%, flag ZLB = True.
During ZLB periods, the balance sheet ROC is the primary L1 signal.
The real policy rate signal is still computed but down-weighted (multiply by 0.5)
because at zero the CB has already maxed out conventional price stimulus.

#### Component Series

| ID | Name | FRED Code | Frequency |
|----|------|-----------|-----------|
| fed_balance_sheet | Fed Balance Sheet | WALCL | Weekly |
| tga | Treasury General Account | WTREGEN | Weekly |
| rrp | Reverse Repo Facility | RRPONTSYD | Daily |

---

### Indicator 2: Real Policy Rate

#### Calculation
```
Real Policy Rate = DFF - Core PCE YoY (PCEPILFE)
```

**Why Core PCE, not headline CPI:**
Core PCE is the Fed's own target measure. It's what the Fed watches when setting policy,
making it the most relevant deflator for predicting the CB reaction function — which is
what the real rate in L1 is measuring. Headline CPI has larger shelter-lag distortions
and is more volatile.

**Parallel market signal (do not blend into score — use as confirmation):**
Fetch `DFII2` (2Y TIPS real yield). When DFF−PCE and DFII2 agree, signal is clean.
When they diverge (market pricing disinflation before CPI data confirms), flag the
divergence as an uncertainty note on the dashboard.

#### Scoring (Discrete View)
| Real Rate | Score | Interpretation |
|-----------|-------|----------------|
| Negative | +1 | CB actively subsidising borrowing |
| 0% to +1% | 0 | Neutral |
| >+1% and rising | −1 | Punitive — suppressing credit creation |

#### ZLB Handling
When ZLB flag = True, real rate signal weight reduced to 0.5.
Display ZLB badge on dashboard when active.

#### Component Series

| ID | Name | FRED Code | Frequency |
|----|------|-----------|-----------|
| fed_funds | Fed Funds Rate | DFF | Daily |
| core_pce | Core PCE YoY | PCEPILFE | Monthly |
| tips_2y | 2Y TIPS Real Yield | DFII2 | Daily (confirmation only, not scored) |

#### Retained for Reference (not scored in L1)
| ID | Name | FRED Code | Notes |
|----|------|-----------|-------|
| cpi | CPI All Items | CPIAUCSL | Cross-check for real rate; used in L2b |
| dgs10 | 10-Year Treasury | DGS10 | Yield curve — candidate for L2a |
| dgs2 | 2-Year Treasury | DGS2 | Yield curve — candidate for L2a |

**L1 Score range: −2 to +2** (one indicator each, net liquidity + real rate)

---

## Layer 2a: Private Credit / Wholesale Liquidity

**9 scored indicators** across wholesale activation, risk appetite, and bank credit expansion.

### Design Decisions
- **WRMFNS replaced with WRMFSL** — WRMFNS is retail MMF only. WRMFSL is total MMF assets
  (retail + institutional). Institutional cash pools (CICPs) are the dominant wholesale
  funding source. Retail is a small fraction. This was a material error in the prior version.
- **MMF signal logic corrected** — raw MMF 12m ROC does not distinguish cash deployed into
  private markets from cash parked at the Fed (RRP). Use deployed cash concept instead.
- **VIX reinstated** — VIX is the best real-time proxy for collateral haircut levels.
  High VIX = haircuts expanding = collateral multiplier contracting = private liquidity
  shrinks even with stable balance sheet sizes. This is the mechanism for non-linear
  liquidity disappearance in crises and must be in L2a.
- **DXY noted but retained as removed** — defensible for a US-only dashboard. Must be
  reinstated when extending to multi-economy version. Flag in code as TODO: global extension.

| ID | Name | FRED Code | Signal Type | Invert | Description |
|----|------|-----------|-------------|--------|-------------|
| rrp_direction | RRP Outstanding | RRPONTSYD | roc_4w | Yes | Falling RRP = cash entering private system |
| sofr_effr_spread | SOFR-EFFR Spread | (derived) | level | Yes | Repo stress — Stage 2 health check |
| mmf_deployed | MMF Deployed Cash | (derived) | roc_12m | No | WRMFSL − RRPONTSYD = cash in private markets |
| primary_dealer_repo | Primary Dealer Repo | NY Fed weekly | roc_12m | No | Dealer balance sheet leverage |
| hy_spread | HY Credit Spread | BAMLH0A0HYM2OAS | level | Yes | Risk appetite / spread compression |
| ig_spread | IG Credit Spread | BAMLC0A0CM | level | Yes | Confirmation |
| nfci | Chicago Fed NFCI | NFCI | level | Yes | Composite financial conditions |
| vix | VIX | VIXCLS | level | Yes | Collateral haircut proxy; high VIX = multiplier contracting |
| bank_credit | Bank Credit Total | TOTLL | roc_12m | No | Total Loans & Leases H.8 |
| ci_loans | C&I Loans | BUSLOANS | roc_12m | No | Business credit — most cyclically sensitive |
| m2 | M2 Money Supply | M2SL | roc_12m | No | Broad money; accelerating = lending creating deposits |

### Derived Series Calculations

#### SOFR-EFFR Spread
```python
spread = (SOFR - EFFR) * 100  # in basis points
```
| Level | Score | Interpretation |
|-------|-------|----------------|
| <5bp | +1 | Normal — system healthy |
| 5–15bp | 0 | Mild stress |
| >15bp | −1 | Repo stress — Stage 2 breaking |

#### MMF Deployed Cash
```python
mmf_deployed = WRMFSL - RRPONTSYD  # both in $ billions
# Then compute 12m ROC on the resulting series
```
Rising deployed cash = liquidity entering private wholesale system.
Rising total MMF assets with rising RRP = abundance but not transmitting.

#### SOFR Data History (Combined Series)
| Period | Source | FRED Code | Notes |
|--------|--------|-----------|-------|
| 2000–2016 | USD LIBOR 3M proxy | TED spread + T-Bill 3M | Includes term/credit premium — less precise |
| 2016–2018 | OBFR | OBFR | Overnight Bank Funding Rate |
| 2018+ | SOFR | SOFR | Secured Overnight Financing Rate |

### Primary Dealer Repo
- Source: NY Fed Primary Dealer Statistics (weekly)
- URL: `https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics`
- Download the repo/reverse repo position series
- Not available on FRED — requires direct NY Fed fetch

---

## Layer 2b: Economic Reality (COUNTERINTUITIVE Scoring)

**Key concept:** Weak economy = CB will ease = **bullish** for future liquidity.
These indicators measure the CB reaction function, not economic health.

| ID | Name | FRED Code | Signal Type | Invert | Description |
|----|------|-----------|-------------|--------|-------------|
| capacity_util | Capacity Utilization | TCU | level | Yes | <78% = slack = CB has room to ease |
| industrial_prod | Industrial Production | INDPRO | roc_12m | Yes | Weak growth = CB eases = bullish |
| unemployment | Unemployment Rate | UNRATE | roc_29m | No | Rising = CB forced to ease = bullish |
| cpi_level | CPI YoY | CPIAUCSL | yoy | Yes | Low inflation = CB can stay loose |
| cpi_momentum | CPI Momentum | CPIAUCSL | momentum | No | Deceleration = CB can ease = bullish |
| ism_prices | ISM Prices Paid | NAPMPRIC | roc_18m | Yes | Sensitive materials — Boucher 18m ROC signal |
| ppi_commodities | PPI All Commodities | PPIACO | roc_12m | Yes | Upstream price pressure — **use ROC not level** |

### Design Decisions
- **ISM Prices Paid added (`NAPMPRIC`)** — this is Boucher's sensitive materials 18m ROC
  indicator. More forward-looking than PPI. Measures upstream commodity/input price
  pressure before it shows up in CPI.
- **PPI corrected to ROC** — prior version scored PPI as level with invert. Correct signal
  is rate of change: high-but-decelerating PPI = bullish (CB will ease); low-but-accelerating
  PPI = bearish. Changed signal type from `level` to `roc_12m`.

### Scoring Thresholds (Discrete View)

| Indicator | Bullish (+1) | Neutral (0) | Bearish (−1) |
|-----------|-------------|-------------|--------------|
| Capacity Util | <78% | 78–81.5% | >81.5% |
| IP 12m ROC | <5% | 5–7% | >7% |
| Unemployment 29m ROC | Rising | Stable | Falling rapidly |
| CPI YoY level | <3.2% | 3.2–5% | >5% |
| CPI Momentum | 3m < 12m (decel) | Flat | 3m > 12m (accel) |
| ISM Prices 18m ROC | <18% | 18–25% | >25% |
| PPI 12m ROC | Negative/low | 0–5% | >5% accelerating |

### CPI Momentum Calculation
```python
momentum = cpi_3m_annualised - cpi_12m_yoy
# Negative = deceleration = bullish
# Positive = acceleration = bearish
```

**L2b Score range: −7 to +7**

---

## Transmission Chain View — NEW VIEW

### Concept
The transmission chain view shows **how far the CB liquidity impulse has traveled**
through the financial system toward the real economy. Rather than three aggregate layer
scores, it shows 7 sequential stages, each with their own indicators, and identifies
where in the chain transmission is flowing versus breaking.

### The 7 Stages

```
Stage 1  CB creates reserves
    ↓
Stage 2  Wholesale markets activate
    ↓
Stage 3  Risk appetite returns / spreads compress
    ↓
Stage 4  Bank credit expands
    ↓
Stage 5  Asset prices respond
    ↓
Stage 6  Real economy responds
    ↓
Stage 7  Inflation builds → cycle reversal warning
```

---

### Stage Definitions and Indicators

#### Stage 1 — CB Impulse Created
*"Did the CB inject?"*
| Indicator | Series | Signal |
|-----------|--------|--------|
| Net Liquidity 12m ROC | WALCL−TGA−RRP | Positive = injecting |
| Real Policy Rate | DFF − PCEPILFE | Negative = accommodative |
| TGA direction | WTREGEN 4w ROC | Falling = releasing cash into system |

**Stage 1 status:** Mean of indicator Z-scores. Positive = CB is pushing.

---

#### Stage 2 — Wholesale Activation
*"Is the plumbing turning over?"*
This is the most critical stage — if it breaks here, nothing downstream will transmit.
| Indicator | Series | Signal |
|-----------|--------|--------|
| RRP direction | RRPONTSYD 4w ROC | Falling = cash leaving Fed |
| SOFR−EFFR spread | Derived | <5bp = healthy |
| MMF Deployed Cash | WRMFSL−RRPONTSYD ROC | Rising = cash in private system |
| Primary Dealer Repo | NY Fed weekly | Rising = dealers leveraging up |
| Excess Reserves direction | EXCSRESNS | Falling = banks deploying |

**Stage 2 status:** Mean of indicator Z-scores.

---

#### Stage 3 — Risk Appetite / Spread Compression
*"Is the market willing to extend credit?"*
| Indicator | Series | Signal |
|-----------|--------|--------|
| HY OAS | BAMLH0A0HYM2OAS | Compressing = risk appetite |
| IG OAS | BAMLC0A0CM | Confirmation |
| VIX | VIXCLS | Falling = haircuts contracting |
| NFCI | NFCI | Negative = loose conditions |

**Stage 3 status:** Mean of indicator Z-scores.

---

#### Stage 4 — Bank Credit Expansion
*"Is it crossing into the real economy?"*
| Indicator | Series | Signal |
|-----------|--------|--------|
| Total Loans 12m ROC | TOTLL | Accelerating |
| C&I Loans 12m ROC | BUSLOANS | Business credit drawing |
| M2 12m ROC | M2SL | Money supply expanding |
| Commercial Paper | COMPAPER | Short-term corporate funding |

**Stage 4 status:** Mean of indicator Z-scores.

---

#### Stage 5 — Asset Price Response
*"Are markets pricing in the liquidity?"*
| Indicator | Series | Signal |
|-----------|--------|--------|
| Copper 12m ROC | HG=F (Yahoo) or FRED PCOPPUSDM | Rising = industrial demand |
| CRB Index 12m ROC | CRB / ^CRB Yahoo | Broad commodity |
| S&P 500 12m ROC | SP500 FRED | Equity repricing |
| Gold 12m ROC | GOLDAMGBD228NLBM FRED | Real rate inverse |

**Stage 5 status:** Mean of indicator Z-scores.
Note: Stage 5 is informational in the chain view — asset prices respond to anticipation
of Stages 1–4, so they can lead the earlier stages. Flag if Stage 5 is green while
Stages 2–4 are red (asset price rally without fundamental transmission = fragile).

---

#### Stage 6 — Real Economy Response
*"Has it reached the ground?"*
| Indicator | Series | Signal |
|-----------|--------|--------|
| Industrial Production 12m ROC | INDPRO | Accelerating |
| Capacity Utilization level | TCU | Rising toward 80% |
| ISM Manufacturing PMI | NAPM FRED | Crossing above 50, rising |
| Unemployment 29m ROC | UNRATE | Falling = demand absorbing labor |

**Stage 6 status:** Mean of indicator Z-scores.

---

#### Stage 7 — Cycle Reversal Warning
*"Is the CB about to tighten?"*
Scored in the **same counterintuitive direction as L2b** — these turning positive
means the cycle is maturing and CB tightening is coming.
| Indicator | Series | Signal (warning = positive) |
|-----------|--------|----------------------------|
| CPI Momentum | CPIAUCSL 3m ann. − 12m | Positive = acceleration |
| CPI Level | CPIAUCSL YoY | >3.2% = pressure building |
| ISM Prices Paid 18m ROC | NAPMPRIC | >18% = upstream inflation |
| Capacity Util level | TCU | >81.5% = running hot |
| Unemployment falling | UNRATE | Below 4% and declining |

**Stage 7 status:** Mean of indicator Z-scores. Rising Stage 7 = cycle peak approaching.

---

### Transmission Chain UI Specification

#### Layout
Vertical or horizontal chain of 7 stage cards, connected by flow arrows.

#### Per-Stage Card Shows
- Stage number and name
- List of indicators with individual signal (green/yellow/red dot + Z-score value)
- Stage aggregate signal (large colored indicator: green/yellow/red)
- Brief interpretation text (one line)

#### Flow Arrow Between Stages
- **Green arrow:** upstream stage positive AND this stage positive — transmission flowing
- **Yellow arrow:** upstream positive but this stage neutral — partial transmission
- **Red arrow with X:** upstream positive but this stage negative — **break detected here**
- **Grey arrow:** upstream stage also negative — break was earlier, this stage not yet relevant

#### Break Detection Logic
```python
def detect_transmission_break(stage_scores):
    """
    Find the first stage where signal turns negative
    after a positive upstream stage.
    Returns: break_stage (int or None), break_severity (float)
    """
    break_stage = None
    for i in range(1, len(stage_scores)):
        if stage_scores[i-1] > 0 and stage_scores[i] < -0.3:
            break_stage = i + 1  # 1-indexed
            break
    return break_stage
```

#### Cycle Position Readout
Below the chain, display a single summary:

| Pattern | Label | Color |
|---------|-------|-------|
| Stages 1–2 green only | Early — impulse created, transmission starting | Blue |
| Stages 1–4 green | Mid cycle — transmission working, credit expanding | Green |
| Stages 1–5 green | Late mid — assets pricing in, real economy next | Yellow-green |
| Stages 1–6 green | Late cycle — fully transmitted, watch Stage 7 | Orange |
| Stage 7 indicators rising | Cycle peak — reversal risk building | Red |
| Stage 1 green, Stage 2 red | Trapped liquidity — QE not transmitting | Red |
| Stage 2 green, Stage 3 red | Wholesale active, risk appetite absent | Red |
| Stage 3 green, Stage 4 red | Spreads tight, banks not lending | Red |
| Stage 5 green, Stages 2–4 red | Asset rally without transmission — fragile | Red warning |

#### Historical Replay
Add a date slider to replay the chain state across history (2000–present).
Shows how the chain evolved through 2008–2009, 2020, 2022–2023.

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

## Complete FRED Series Reference

| Code | Name | Frequency | Used In |
|------|------|-----------|---------|
| WALCL | Fed Total Assets | Weekly | L1, Stage 1 |
| WTREGEN | Treasury General Account | Weekly | L1, Stage 1 |
| RRPONTSYD | Reverse Repo | Daily | L1 (drain), L2a, Stage 2 |
| DFF | Fed Funds Rate | Daily | L1 real rate |
| PCEPILFE | Core PCE YoY | Monthly | L1 real rate |
| DFII2 | 2Y TIPS Real Yield | Daily | L1 confirmation (not scored) |
| CPIAUCSL | CPI All Items | Monthly | L2b, Stage 7 |
| DGS10 | 10Y Treasury | Daily | Reference only (L2a candidate) |
| DGS2 | 2Y Treasury | Daily | Reference only (L2a candidate) |
| WRMFSL | MMF Total Assets (ALL) | Weekly | L2a Stage 2 — **not WRMFNS** |
| EXCSRESNS | Excess Reserves | Monthly | Stage 2 |
| TOTLL | Bank Credit | Weekly | L2a, Stage 4 |
| BUSLOANS | C&I Loans | Monthly | L2a, Stage 4 |
| M2SL | M2 Money Supply | Monthly | L2a, Stage 4 |
| COMPAPER | Commercial Paper | Weekly | Stage 4 |
| BAMLH0A0HYM2OAS | HY Spread | Daily | L2a, Stage 3 |
| BAMLC0A0CM | IG Spread | Daily | L2a, Stage 3 |
| NFCI | Financial Conditions | Weekly | L2a, Stage 3 |
| VIXCLS | VIX | Daily | L2a, Stage 3 |
| SOFR | Secured O/N Rate | Daily | L2a spread calc |
| EFFR | Effective Fed Funds | Daily | L2a spread calc |
| TCU | Capacity Utilization | Monthly | L2b, Stage 6+7 |
| INDPRO | Industrial Production | Monthly | L2b, Stage 6 |
| UNRATE | Unemployment Rate | Monthly | L2b, Stage 6+7 |
| NAPMPRIC | ISM Prices Paid | Monthly | L2b, Stage 7 |
| PPIACO | PPI All Commodities | Monthly | L2b (ROC, not level) |
| NAPM | ISM Manufacturing PMI | Monthly | Stage 6 |
| SP500 | S&P 500 | Daily | Stage 5 |
| GOLDAMGBD228NLBM | Gold Price | Daily | Stage 5 |
| PCOPPUSDM | Copper Price | Monthly | Stage 5 |

### External Sources (non-FRED)
| Source | Data | URL | Frequency |
|--------|------|-----|-----------|
| NY Fed | Primary Dealer Repo | https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics | Weekly |
| Yahoo Finance | CRB Index `^CRB` | via yfinance | Daily |
| Yahoo Finance | Copper `HG=F` | via yfinance | Daily |

### Data Cache
- Raw series: `data/liquidity/us_liquidity_raw.csv`
- Derived series (ROC, Z-scores): `data/liquidity/us_liquidity_derived.csv`
- **Cache raw and derived separately** — stale derived cache can silently feed wrong
  Z-score windows. Always recompute derived from raw on load.
- API key: `data/fred_api_key.txt`

---

## File Structure

```
src/analysis/liquidity_monitoring/
├── streamlit_app.py                  # Main app entry point
├── config/
│   └── indicators.py                 # Indicator definitions & weights
├── calculations/
│   ├── liquidity_indicators.py       # ROC, Z-score, scoring functions
│   ├── regime_classifier.py          # Discrete regime classification
│   └── transmission_chain.py         # NEW: Stage scoring + break detection
├── data/
│   └── loader.py                     # FRED + NY Fed data fetching & caching
├── views/
│   ├── dashboard.py                  # Main dashboard view
│   ├── layer_detail.py               # Layer breakdown view
│   └── transmission_chain_view.py    # NEW: Chain view rendering
```

---

## Key Functions

### Existing
### `calculate_net_liquidity(walcl, tga, rrp, smooth=True, ema_span=10)`
Computes Fed Net Liquidity with EMA smoothing, excluding RRP pre-2010.

### `calculate_continuous_indicator_score(series, config)`
Converts raw series to Z-score normalized measure, handling frequency detection and inversion.

### `calculate_historical_continuous_totals(raw_data, l1_config, l2a_config, l2b_config)`
Calculates historical layer scores as mean of Z-scores, forward-fills to align frequencies.

### `calculate_roc_12m(series)`
12-month rate of change with auto-frequency detection (12/52/252 periods).

### New Functions Required
### `calculate_stage_scores(raw_data, date) → dict[int, float]`
Returns Z-score for each of the 7 stages at a given date.
Uses stage indicator definitions from Section: Transmission Chain View.

### `detect_transmission_break(stage_scores) → tuple[int|None, str]`
Returns (break_stage, regime_label) from the stage score dict.
Returns None if transmission is flowing or if Stage 1 is negative (no impulse to transmit).

### `calculate_mmf_deployed(wrmfsl, rrpontsyd) → pd.Series`
Returns WRMFSL − RRPONTSYD aligned on common date index.
Apply 12m ROC to result for the L2a signal.

### `get_real_policy_rate(dff, pcepilfe, zlb_threshold=0.25) → tuple[pd.Series, pd.Series]`
Returns (real_rate_series, zlb_flag_series).
ZLB flag = True when DFF ≤ zlb_threshold.

---

## Interpretation Guide

### Z-Score Levels
| Z-Score | Interpretation |
|---------|----------------|
| > +2 | Extremely bullish |
| +1 to +2 | Bullish |
| −1 to +1 | Neutral |
| −2 to −1 | Bearish |
| < −2 | Extremely bearish |

### Composite Score
| Score | Bias |
|-------|------|
| > +0.5 | Bullish |
| −0.5 to +0.5 | Neutral |
| < −0.5 | Bearish |

### Layer Interaction Matrix
| L1 | L2a | L2b | Regime |
|----|-----|-----|--------|
| + | + | + | Early cycle — maximum bullish |
| + | + | − | Late easing — economy recovering, wholesale amplifying |
| + | − | + | Transmission broken — CB easing not flowing through |
| − | + | − | Late cycle — tightening into hot economy |
| − | − | + | Contraction — CB tightening, economy weakening |
| − | − | − | Maximum contraction |

---

## Version History

- **2026-03-13:** Initial Z-score continuous view implementation
- **2026-03-13:** L1 simplified to Net Liquidity only
- **2026-03-13:** Fixed pre-2010 jitter (excluded RRP, 10-period EMA)
- **2026-03-13:** Fixed WRMFSL → WRMFNS (MMF data update)
- **2026-03-13:** Extended SOFR history with USD LIBOR 3M (2000-2016)
- **2026-03-13:** Removed DXY and VIX from L2a
- **2026-03-13:** Fixed ROC frequency detection for monthly data
- **2026-03-24:** L1 — Added Real Policy Rate (DFF − Core PCE) as second L1 indicator
- **2026-03-24:** L1 — Removed yield curve (endogenous to liquidity, moved to L2a candidate)
- **2026-03-24:** L1 — Added ZLB flag logic (down-weight real rate when DFF ≤ 0.25%)
- **2026-03-24:** L1 — Added DFII2 (2Y TIPS) as unscored confirmation signal
- **2026-03-24:** L2a — Fixed WRMFNS → WRMFSL (total MMF, not retail only — material error)
- **2026-03-24:** L2a — Added MMF Deployed Cash derived series (WRMFSL − RRPONTSYD)
- **2026-03-24:** L2a — Reinstated VIX as collateral haircut proxy
- **2026-03-24:** L2a — Added RRP direction as standalone signal (4w ROC)
- **2026-03-24:** L2a — Added Primary Dealer Repo (NY Fed) as Stage 2 wholesale signal
- **2026-03-24:** L2b — Added ISM Prices Paid (NAPMPRIC) as Boucher sensitive materials indicator
- **2026-03-24:** L2b — Fixed PPI signal type from level to roc_12m
- **2026-03-24:** NEW — Transmission Chain View (7-stage flow visualisation)
- **2026-03-24:** Cache — Separated raw and derived series caching