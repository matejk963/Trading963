# Global Liquidity Monitoring Framework — Agent Context File
## Purpose
This file instructs a data-fetching and relevance-testing agent on which indicators to collect,
from which sources, at what frequency, and how they fit into a three-layer liquidity framework
derived from Michael Howell's Global Liquidity Index (GLI) methodology (Capital Wars, 2020)
combined with Mark Boucher's Austrian Liquidity Cycle (The Hedge Fund Edge, 1999).

The agent's job is to:
1. Fetch all series listed below
2. Compute derived signals as specified
3. Test each indicator's predictive relevance against the target economic variables and asset classes listed in Section 4
4. Score and rank indicators by predictive power (lead time, Granger causality, correlation structure)

---

## FRAMEWORK OVERVIEW

### Causal Chain
```
CB sets price/quantity of money (Layer 1 — impulse)
        ↓
Private wholesale system amplifies or dampens (Layer 2a — transmission)
        ↓
Real economy responds with 12–18 month lag (Layer 2b — feedback)
        ↓
CB reads economic data and adjusts → cycle repeats
```

### Three Layers
- **Layer 1 — CB Liquidity:** Exogenous impulse. Balance sheet changes, net liquidity, real policy rate, yield curve.
- **Layer 2a — Private Sector / Wholesale Liquidity:** Amplitude and transmission. Bank credit, shadow banking, repo markets, cross-currency dynamics.
- **Layer 2b — Economic Reality Gauges:** Feedback loop and CB reaction function. Scored counterintuitively — weak economy = CB will ease = bullish liquidity signal.

### Scoring convention (for composite index construction)
Each indicator is scored **+1 / 0 / −1** per thresholds defined below.
All raw series should also be retained in normalised form (12m ROC, then Z-score within own history) for regression/Granger testing.

---

## SECTION 1 — LAYER 1: CENTRAL BANK LIQUIDITY

### 1.1 UNITED STATES (Fed)

| ID | Series Name | FRED Code / Source | Frequency | Derivation / Signal |
|----|------------|-------------------|-----------|-------------------|
| US-CB-1 | Fed Balance Sheet (WALCL) | `WALCL` FRED | Weekly | 12m ROC: +1 expanding / −1 shrinking |
| US-CB-2 | Fed Net Liquidity | Calculated: WALCL − WTREGEN − RRPONTSYD | Weekly | 12m ROC: +1 expanding / −1 shrinking |
| US-CB-3 | Treasury General Account (TGA) | `WTREGEN` FRED | Weekly | Rising TGA = drain on reserves = tightening |
| US-CB-4 | Reverse Repo (RRP) | `RRPONTSYD` FRED | Daily | Rising RRP = liquidity drain from system |
| US-CB-5 | Fed Funds Rate (nominal) | `DFF` FRED | Daily | Used in real rate calculation |
| US-CB-6 | CPI YoY | `CPIAUCSL` FRED (compute YoY) | Monthly | Real rate = DFF − CPI YoY |
| US-CB-7 | Real Policy Rate | Derived: DFF − CPI YoY | Monthly | +1 if negative / 0 if 0–1% / −1 if >1% and rising |
| US-CB-8 | 10Y Treasury | `DGS10` FRED | Daily | Yield curve component |
| US-CB-9 | 2Y Treasury | `DGS2` FRED | Daily | Yield curve component |
| US-CB-10 | Yield Curve 10Y−2Y | Derived: DGS10 − DGS2 | Daily | +1 if >150bp steepening / 0 flat / −1 inverted |

**Layer 1 US Score range: −4 to +4**

---

### 1.2 EUROZONE (ECB)

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| EU-CB-1 | ECB Total Assets | ECB Data Portal: `ILM.W.U2.C.A000000.Z5.Z01` | Weekly | 12m ROC |
| EU-CB-2 | ECB Deposit Facility Usage | ECB Data Portal: `FM.B.U2.EUR.4F.KR.DFR.LEV` | Daily | Rising = banks parking cash, transmission weak |
| EU-CB-3 | ECB Deposit Facility Rate | ECB Data Portal | Daily | Nominal policy rate |
| EU-CB-4 | Eurozone HICP YoY | Eurostat / ECB `ICP.M.U2.N.000000.4.ANR` | Monthly | Real rate calculation |
| EU-CB-5 | Real ECB Rate | Derived: DFR − HICP YoY | Monthly | +1 negative / 0 near zero / −1 >1% rising |
| EU-CB-6 | German 10Y Bund | ECB Data Portal `FM.M.DE.EUR.FR.BB.GVB.IP10Y.YLD` or FRED `IRLTLT01DEM156N` | Daily | Yield curve anchor |
| EU-CB-7 | German 2Y Schatz | ECB Data Portal | Daily | Yield curve component |
| EU-CB-8 | EA Yield Curve 10Y−2Y | Derived | Daily | Same scoring as US |
| EU-CB-9 | TLTRO Outstanding | ECB Data Portal | Monthly | Targeted lending ops = directed liquidity injection |

---

### 1.3 JAPAN (BoJ)

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| JP-CB-1 | BoJ Balance Sheet Total Assets | BoJ `BS01'MABJMTA` | Monthly | 12m ROC |
| JP-CB-2 | BoJ Current Account Balances (Excess Reserves) | BoJ Statistics | Daily | Excess reserves level |
| JP-CB-3 | BoJ Policy Rate (overnight) | BoJ | Daily | Nominal policy rate |
| JP-CB-4 | Japan CPI YoY | Statistics Japan (MIC) / FRED `JPNCPIALLMINMEI` | Monthly | Real rate calculation |
| JP-CB-5 | Real BoJ Rate | Derived: BoJ rate − CPI YoY | Monthly | +1 negative / 0 near zero / −1 >1% rising |
| JP-CB-6 | JGB 10Y | BoJ / FRED `IRLTLT01JPM156N` | Daily | Yield curve anchor; note YCC targeting complicates signal |
| JP-CB-7 | JGB 2Y | BoJ | Daily | Yield curve component |
| JP-CB-8 | Japan Yield Curve 10Y−2Y | Derived | Daily | Same scoring; YCC distortion flag |
| JP-CB-9 | BoJ JGB Holdings % of total outstanding | BoJ | Monthly | >50% = market distortion flag |

**Note:** Japan Yield Curve Control (YCC) policy means yield curve spread is administratively managed — weight this signal lower or flag as distorted when BoJ is actively capping 10Y yields.

---

### 1.4 UNITED KINGDOM (BoE)

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| UK-CB-1 | BoE Balance Sheet Total Assets | BoE Statistical Interactive Database `RPQB6RJ` | Weekly | 12m ROC |
| UK-CB-2 | BoE Bank Rate | BoE `IUDBEDR` | Daily | Nominal policy rate |
| UK-CB-3 | UK CPI YoY | ONS / FRED `GBRCPIALLMINMEI` | Monthly | Real rate calculation |
| UK-CB-4 | Real BoE Rate | Derived: Bank Rate − CPI YoY | Monthly | +1 negative / 0 near zero / −1 >1% rising |
| UK-CB-5 | Gilt 10Y | BoE / FRED `IRLTLT01GBM156N` | Daily | Yield curve anchor |
| UK-CB-6 | Gilt 2Y | BoE | Daily | Yield curve component |
| UK-CB-7 | UK Yield Curve 10Y−2Y | Derived | Daily | Standard scoring |
| UK-CB-8 | APF (QE) Holdings | BoE `RPQB6RJ` asset purchase facility | Weekly | Size and direction of QE/QT |

---

### 1.5 CANADA (BoC)

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| CA-CB-1 | BoC Total Assets | BoC Banking and Financial Statistics Table C1 | Weekly | 12m ROC |
| CA-CB-2 | BoC Overnight Rate Target | BoC / FRED `IRSTCB01CAM156N` | Daily | Nominal policy rate |
| CA-CB-3 | Canada CPI YoY | StatsCan / FRED `CANCPIALLMINMEI` | Monthly | Real rate calculation |
| CA-CB-4 | Real BoC Rate | Derived | Monthly | Standard scoring |
| CA-CB-5 | Canada 10Y GoC Bond | BoC / FRED `IRLTLT01CAM156N` | Daily | Yield curve anchor |
| CA-CB-6 | Canada 2Y GoC Bond | BoC | Daily | Yield curve component |
| CA-CB-7 | Canada Yield Curve 10Y−2Y | Derived | Daily | Standard scoring |

---

### 1.6 AUSTRALIA (RBA)

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| AU-CB-1 | RBA Total Assets | RBA Statistical Tables A01 | Weekly | 12m ROC |
| AU-CB-2 | RBA Exchange Settlement (ES) Balances | RBA A01 | Daily | Proxy for excess reserves in no-reserve-requirement system |
| AU-CB-3 | RBA Cash Rate Target | RBA / FRED `IRSTCB01AUM156N` | Daily | Nominal policy rate |
| AU-CB-4 | Australia CPI YoY | ABS / FRED `AUSCPIALLQINMEI` | Quarterly (note: quarterly not monthly) | Real rate calculation |
| AU-CB-5 | Real RBA Rate | Derived | Quarterly | Standard scoring |
| AU-CB-6 | AGB 10Y | RBA / FRED `IRLTLT01AUM156N` | Daily | Yield curve anchor |
| AU-CB-7 | AGB 3Y | RBA (3Y is more liquid benchmark in Australia) | Daily | Yield curve component; use 3Y−cash as alternative spread |
| AU-CB-8 | Australia Yield Curve 10Y−3Y | Derived | Daily | Standard scoring adapted |

---

### 1.7 NEW ZEALAND (RBNZ)

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| NZ-CB-1 | RBNZ Total Assets | RBNZ Statistical Tables B1 | Monthly | 12m ROC |
| NZ-CB-2 | RBNZ OCR (Official Cash Rate) | RBNZ / FRED `IRSTCB01NZM156N` | Daily | Nominal policy rate |
| NZ-CB-3 | New Zealand CPI YoY | StatsNZ / FRED `NZLCPIALLQINMEI` | Quarterly | Real rate calculation |
| NZ-CB-4 | Real RBNZ Rate | Derived | Quarterly | Standard scoring |
| NZ-CB-5 | NZGB 10Y | RBNZ / FRED `IRLTLT01NZM156N` | Daily | Yield curve anchor |
| NZ-CB-6 | NZGB 2Y | RBNZ | Daily | Yield curve component |
| NZ-CB-7 | NZ Yield Curve 10Y−2Y | Derived | Daily | Standard scoring |

---

## SECTION 2 — LAYER 2a: PRIVATE SECTOR / WHOLESALE LIQUIDITY

### 2.1 GLOBAL SIGNALS (apply to all economies — measure once, use everywhere)

These series capture the global Eurodollar wholesale system that overrides local CB policy for non-US economies.

| ID | Series Name | Source | Frequency | Derivation / Signal |
|----|------------|--------|-----------|-------------------|
| GL-WS-1 | DXY (US Dollar Index) | FRED `DTWEXBGS` (broad) or Yahoo Finance `DX-Y.NYB` | Daily | 12m ROC: +1 weakening / 0 stable / −1 strengthening |
| GL-WS-2 | EUR/USD Cross-Currency Basis | Reconstruct: EUR/USD 3M fwd implied rate − USD LIBOR/SOFR equivalent. Bloomberg `EURUSD3M Curncy` if available; else: (EUR/USD fwd − EUR/USD spot)/spot × (360/days) − (USD rate − EUR rate) | Daily | +1 compressing toward zero / 0 stable / −1 widening more negative |
| GL-WS-3 | JPY/USD Cross-Currency Basis | Same methodology for JPY. BoJ publishes JPY/USD FX swap rates. | Daily | Same scoring |
| GL-WS-4 | Global HY Credit Spread | FRED `BAMLH0A0HYM2OAS` (US HY OAS) | Daily | +1 <400bp compressing / 0 stable / −1 >600bp widening |
| GL-WS-5 | US IG Credit Spread | FRED `BAMLC0A0CM` | Daily | Directional confirmation |
| GL-WS-6 | VIX | FRED `VIXCLS` | Daily | Proxy for collateral haircut level — high VIX = collateral multiplier collapsing |
| GL-WS-7 | BIS Cross-Border Bank Lending YoY | `data.bis.org` Locational Banking Statistics Table A1 | Quarterly | 12m ROC: +1 expanding / −1 contracting |
| GL-WS-8 | US SOFR Daily Volume | NY Fed (published daily) | Daily | Money market flow volume — low volume = stress |
| GL-WS-9 | SOFR − EFFR Spread | Derived: SOFR − `DFF` FRED | Daily | +1 <5bp / 0 5–15bp / −1 >15bp = repo stress |
| GL-WS-10 | US Primary Dealer Repo Book | NY Fed weekly primary dealer statistics | Weekly | Direction and size of dealer balance sheet leverage |
| GL-WS-11 | Fed RRP Outstanding | `RRPONTSYD` FRED | Daily | High RRP = excess cash with nowhere to go = liquidity abundance but not transmitting |
| GL-WS-12 | US MMF Total Assets | `WRMFSL` FRED | Weekly | Proxy for CICP (corporate/institutional cash pool) size |
| GL-WS-13 | US Commercial Paper Outstanding | FRED `COMPAPER` | Weekly | Short-term unsecured wholesale funding |

---

### 2.2 LOCAL WHOLESALE SIGNALS — PER ECONOMY

#### United States
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| US-PS-1 | Commercial Bank Credit Total | `TOTLL` FRED (H.8) | Weekly | 12m ROC: +1 accelerating / 0 stable / −1 contracting |
| US-PS-2 | C&I Loans | `BUSLOANS` FRED | Weekly | Business credit directional |
| US-PS-3 | Real Estate Loans | `REALLN` FRED | Weekly | Housing credit directional |
| US-PS-4 | Consumer Credit | `TOTALSL` FRED | Monthly | Consumer credit directional |
| US-PS-5 | M2 Money Supply | `M2SL` FRED | Weekly | Broad money 12m ROC |
| US-PS-6 | Bank Excess Reserves | `EXCSRESNS` FRED | Monthly | Watch $1.5T threshold flagged by Howell |
| US-PS-7 | Z.1 Total Credit Market | Fed Z.1 Financial Accounts Table D.3 | Quarterly | Gross balance sheet — most comprehensive private liquidity measure |
| US-PS-8 | Agency MBS Outstanding | FRED `MBST` | Monthly | GSE/securitisation channel |
| US-PS-9 | Chicago Fed NFCI | `NFCI` FRED | Weekly | Composite financial conditions — negative = loose |
| US-PS-10 | Bank Lending Survey (SLOOS) | Fed Senior Loan Officer Survey | Quarterly | Credit standards: tightening = negative for liquidity |

#### Eurozone (aggregate; country breakdowns available in ECB portal by same series)
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| EU-PS-1 | MFI Loans to Private Sector | ECB `BSI.M.U2.N.A.A20.A.1.U2.2240.Z01.E` | Monthly | 12m ROC |
| EU-PS-2 | MFI Loans to NFCs | ECB Data Portal (filter by NFC counterpart) | Monthly | Business credit |
| EU-PS-3 | MFI Loans to Households | ECB Data Portal | Monthly | Consumer/mortgage credit |
| EU-PS-4 | M3 Eurozone | ECB `BSI.M.U2.Y.V.M30.X.I.U2.2300.Z01.E` | Monthly | Broad money 12m ROC |
| EU-PS-5 | ECB Bank Lending Survey | ECB quarterly publication | Quarterly | Credit standards direction |
| EU-PS-6 | €STR − ECB Deposit Rate | Derived: €STR − DFR | Daily | Repo stress indicator |
| EU-PS-7 | EA Sectoral Financial Accounts | ECB / Eurostat `nasq_10_f_bs` | Quarterly | Flow of funds equivalent |
| EU-PS-8 | Covered Bond Issuance (Pfandbrief) | ECB / ECBC (European Covered Bond Council) | Monthly | German shadow bank proxy |
| EU-PS-9 | Investment Fund Assets EA | ECB Statistical Data Warehouse `IVF` tables | Monthly | OFI / shadow bank size |

#### Japan
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| JP-PS-1 | Bank Lending YoY | BoJ `BS01'MABJMA3` | Monthly | 12m ROC |
| JP-PS-2 | M3 Japan | BoJ | Monthly | Broad money |
| JP-PS-3 | Commercial Paper Outstanding | BoJ | Monthly | Wholesale funding |
| JP-PS-4 | TONAR − BoJ Rate | Derived: TONAR − BoJ overnight rate | Daily | Repo stress |
| JP-PS-5 | BoJ Flow of Funds | BoJ Statistics: Flow of Funds Accounts | Quarterly | Sectoral balance sheets |
| JP-PS-6 | FILP (Fiscal Investment & Loan Program) | MOF Japan | Quarterly | Quasi-public credit channel — include in monetary authority aggregate |

#### United Kingdom
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| UK-PS-1 | M4 Lending (excl. intermediate OFCs) | BoE `LPMVTVXA` | Monthly | 12m ROC — best UK private credit measure |
| UK-PS-2 | M4 Broad Money | BoE `LPMAUYN` | Monthly | Broad money |
| UK-PS-3 | Net Consumer Credit | BoE `LPMBC57` | Monthly | Consumer credit flow |
| UK-PS-4 | Mortgage Approvals | BoE `LPMBI22` | Monthly | Housing credit leading indicator |
| UK-PS-5 | SONIA − BoE Rate | Derived: SONIA − Bank Rate | Daily | Repo stress |
| UK-PS-6 | UK Financial Accounts (FoF) | BoE / ONS `MQ5L` | Quarterly | Sectoral balance sheets |
| UK-PS-7 | Credit Conditions Survey | BoE | Quarterly | Credit standards — availability and demand |

#### Canada
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| CA-PS-1 | Total Household Credit | BoC `CREDIT_TOTAL_HOUSEHOLD` | Monthly | 12m ROC |
| CA-PS-2 | Business Credit | BoC credit aggregates | Monthly | Business credit directional |
| CA-PS-3 | M3 Canada | BoC `M3GROSSNSAxx` | Monthly | Broad money |
| CA-PS-4 | CORRA − BoC Rate | Derived: CORRA − overnight rate target | Daily | Repo stress |
| CA-PS-5 | National Balance Sheet Accounts | Statistics Canada Table 36-10-0580-01 | Quarterly | Canada's Z.1 equivalent |
| CA-PS-6 | CMHC Mortgage Insurance Activity | CMHC Housing Market Information Portal | Monthly | GSE-equivalent channel — housing credit amplification |

#### Australia
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| AU-PS-1 | Credit to Private Sector — Housing | RBA D.2 (Housing credit) | Monthly | 12m ROC |
| AU-PS-2 | Credit to Private Sector — Business | RBA D.2 (Business credit) | Monthly | Business credit |
| AU-PS-3 | Credit to Private Sector — Personal | RBA D.2 | Monthly | Consumer credit |
| AU-PS-4 | Broad Money M3 | RBA D.3 | Monthly | Broad money 12m ROC |
| AU-PS-5 | AONIA − RBA Cash Rate | Derived: AONIA − cash rate target | Daily | Repo stress (note: no reserve requirements) |
| AU-PS-6 | RMBS Issuance | RBA / APRA / ASF (Australian Securitisation Forum) | Monthly | Securitisation/shadow bank channel — key in Australia |
| AU-PS-7 | APRA ADI Total Assets | APRA Monthly ADI Statistics | Monthly | Full banking system balance sheet |
| AU-PS-8 | Financial Accounts | ABS 5232.0 | Quarterly | Sectoral balance sheets |

#### New Zealand
| ID | Series | Source | Frequency | Signal |
|----|--------|--------|-----------|--------|
| NZ-PS-1 | Registered Bank Lending — Housing | RBNZ S40 | Monthly | 12m ROC |
| NZ-PS-2 | Registered Bank Lending — Business | RBNZ S40 | Monthly | Business credit |
| NZ-PS-3 | M3 New Zealand | RBNZ S10 | Monthly | Broad money |
| NZ-PS-4 | NZONIA − OCR | Derived: NZONIA − OCR | Daily | Repo stress |
| NZ-PS-5 | Financial Accounts NZ | Stats NZ | Quarterly | Sectoral balance sheets |
| NZ-PS-6 | LVR Restriction Data | RBNZ housing lending data | Monthly | Regulatory tightening signal unique to NZ |

---

### 2.3 CROSS-COUNTRY ANCHOR (BIS — same methodology for all)

| ID | Series | Source | Frequency | Notes |
|----|--------|--------|-----------|-------|
| BIS-1 | Credit to Private Non-Financial Sector — US | BIS data.bis.org Table C2 | Quarterly | Comparable across all countries |
| BIS-2 | Credit to Private Non-Financial Sector — Japan | BIS C2 | Quarterly | Same |
| BIS-3 | Credit to Private Non-Financial Sector — EA | BIS C2 | Quarterly | Same |
| BIS-4 | Credit to Private Non-Financial Sector — UK | BIS C2 | Quarterly | Same |
| BIS-5 | Credit to Private Non-Financial Sector — Canada | BIS C2 | Quarterly | Same |
| BIS-6 | Credit to Private Non-Financial Sector — Australia | BIS C2 | Quarterly | Same |
| BIS-7 | Credit to Private Non-Financial Sector — NZ | BIS C2 | Quarterly | Same |
| BIS-8 | Credit-to-GDP Gap — all countries | BIS data.bis.org Table E1 | Quarterly | BIS early warning indicator; positive = credit boom |
| BIS-9 | Global Liquidity Indicators (BIS GLI) | BIS data.bis.org Table E2 | Quarterly | Foreign currency credit USD/EUR/JPY to non-banks globally |
| BIS-10 | Cross-Border Bank Lending by Country | BIS Locational Banking Statistics A1 | Quarterly | Cross-border transmission — critical for NZ/AU/EA |

---

## SECTION 3 — LAYER 2b: ECONOMIC REALITY GAUGES

### Scoring Convention — COUNTERINTUITIVE
These are scored from the perspective of **what will force CB action**, not from an economic health perspective.
Weak economy = CB must ease = **bullish liquidity signal = +1**
Strong overheating economy = CB must tighten = **bearish liquidity signal = −1**

**Layer 2b Score range: −7 to +7**

### 3.1 UNITED STATES

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| US-ER-1 | Capacity Utilization | `TCU` FRED | Monthly | +1 if <78% / 0 if 78–81.5% / −1 if >81.5% |
| US-ER-2 | Industrial Production 12m ROC | `INDPRO` FRED | Monthly | +1 if <5% / 0 if 5–7% / −1 if >7% |
| US-ER-3 | Unemployment Rate 29m ROC | `UNRATE` FRED | Monthly | +1 if rising (softening labor) / 0 if stable / −1 if falling rapidly (<4% and declining) |
| US-ER-4 | CPI Fast vs Slow ROC | `CPIAUCSL` FRED — compute 3m annualised vs 12m | Monthly | +1 if 3m rate < 12m rate (deceleration) / −1 if 3m > 12m (acceleration) |
| US-ER-5 | CPI Level | `CPIAUCSL` FRED YoY | Monthly | +1 if <3.2% / 0 if 3.2–5% / −1 if >5% |
| US-ER-6 | CRB Commodity Index 12m ROC | CRB Index (Yahoo `^CRB` or Refinitiv) | Daily | +1 if <5% / 0 if 5–10% / −1 if >10% |
| US-ER-7 | Sensitive Materials 18m ROC | ISM Prices Paid `NAPMPRIC` FRED or CRB raw industrials subindex | Monthly | +1 if <18% / −1 if >18% |

---

### 3.2 EUROZONE

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| EU-ER-1 | EA Capacity Utilization | Eurostat `ei_bsin_q_r2` | Quarterly | +1 if <78% / 0 if 78–82% / −1 if >82% |
| EU-ER-2 | EA Industrial Production 12m ROC | Eurostat `sts_inpr_m` / FRED `PRMNTO01EZM661N` | Monthly | +1 if <5% / 0 if 5–7% / −1 if >7% |
| EU-ER-3 | EA Unemployment 29m ROC | Eurostat `une_rt_m` | Monthly | Same counterintuitive scoring |
| EU-ER-4 | EA HICP Fast vs Slow ROC | ECB / Eurostat HICP — compute 3m ann. vs 12m | Monthly | +1 if 3m < 12m / −1 if 3m > 12m |
| EU-ER-5 | EA HICP Level | ECB / FRED `CP0000EZ17M086NEST` | Monthly | +1 if <3.2% / 0 if 3.2–5% / −1 if >5% |
| EU-ER-6 | EA PPI 12m ROC | Eurostat `sts_inppd_m` | Monthly | Sensitive materials proxy |
| EU-ER-7 | EA PMI Manufacturing | S&P Global / Markit EA Manufacturing PMI | Monthly | +1 if <50 / 0 if 50–55 / −1 if >55 (inverted: weak PMI = CB eases) |

---

### 3.3 JAPAN

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| JP-ER-1 | Japan Capacity Utilization | METI / FRED `JPNPROINDQISMEI` (proxy) | Monthly | Standard thresholds |
| JP-ER-2 | Japan Industrial Production 12m ROC | METI / FRED `JPNPROINDQISMEI` | Monthly | Standard |
| JP-ER-3 | Japan Unemployment 29m ROC | Statistics Japan / FRED `LRHUTTTTJPM156S` | Monthly | Standard counterintuitive |
| JP-ER-4 | Japan CPI Fast vs Slow ROC | Statistics Japan / FRED `JPNCPIALLMINMEI` | Monthly | Standard |
| JP-ER-5 | Japan CPI Level | FRED `JPNCPIALLMINMEI` | Monthly | Note: Japan's threshold lower; use +1 if <1% / 0 if 1–3% / −1 if >3% given deflationary history |
| JP-ER-6 | Japan CGPI (Corporate Goods Price Index) 12m ROC | BoJ | Monthly | Sensitive materials proxy |
| JP-ER-7 | Tankan DI (Large Manufacturers) | BoJ Quarterly Tankan | Quarterly | +1 if <0 / 0 if 0–15 / −1 if >15 (same inversion logic) |

---

### 3.4 UNITED KINGDOM

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| UK-ER-1 | UK Capacity Utilization | BoE / CBI survey | Quarterly | Standard thresholds |
| UK-ER-2 | UK Industrial Production 12m ROC | ONS / FRED `GBRIPMAINMEI` | Monthly | Standard |
| UK-ER-3 | UK Unemployment 29m ROC | ONS / FRED `LRUNTTTTGBM156S` | Monthly | Standard counterintuitive |
| UK-ER-4 | UK CPI Fast vs Slow ROC | ONS / FRED `GBRCPIALLMINMEI` | Monthly | Standard |
| UK-ER-5 | UK CPI Level | ONS / FRED `GBRCPIALLMINMEI` | Monthly | Standard thresholds |
| UK-ER-6 | UK PPI Output 12m ROC | ONS | Monthly | Sensitive materials proxy |
| UK-ER-7 | UK PMI Manufacturing | S&P Global / Markit | Monthly | Inverted scoring as per EA |

---

### 3.5 CANADA

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| CA-ER-1 | Canada Capacity Utilization | Statistics Canada `Table 16-10-0004-01` | Quarterly | Standard |
| CA-ER-2 | Canada Industrial Production 12m ROC | FRED `CANPROINDQISMEI` | Monthly | Standard |
| CA-ER-3 | Canada Unemployment 29m ROC | Statistics Canada / FRED `LRUNTTTTCAM156S` | Monthly | Standard counterintuitive |
| CA-ER-4 | Canada CPI Fast vs Slow ROC | Statistics Canada / FRED `CANCPIALLMINMEI` | Monthly | Standard |
| CA-ER-5 | Canada CPI Level | FRED `CANCPIALLMINMEI` | Monthly | Standard thresholds |
| CA-ER-6 | Canada IPPI (Industrial Product Price Index) 12m ROC | Statistics Canada | Monthly | Sensitive materials proxy |
| CA-ER-7 | Canada PMI Manufacturing (Ivey) | Ivey Business School | Monthly | Inverted scoring |

---

### 3.6 AUSTRALIA

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| AU-ER-1 | Australia Capacity Utilization | NAB Business Survey / ABS | Quarterly | Standard |
| AU-ER-2 | Australia Industrial Production 12m ROC | ABS / FRED `AUSPROINDQISMEI` | Quarterly (note: quarterly in AU) | Standard |
| AU-ER-3 | Australia Unemployment 29m ROC | ABS / FRED `LRUNTTTTAUM156S` | Monthly | Standard counterintuitive |
| AU-ER-4 | Australia CPI Fast vs Slow ROC | ABS / FRED `AUSCPIALLQINMEI` | Quarterly | Standard |
| AU-ER-5 | Australia CPI Level | ABS / FRED `AUSCPIALLQINMEI` | Quarterly | Standard thresholds |
| AU-ER-6 | Australia PPI 12m ROC | ABS Producer Price Index | Quarterly | Sensitive materials proxy |
| AU-ER-7 | Australia PMI Manufacturing | Judo Bank / S&P Global | Monthly | Inverted scoring |

**Note:** Australia reports CPI and many activity measures quarterly not monthly — this creates a data lag disadvantage. Use NAB Business Confidence / AIG Manufacturing PMI as higher-frequency proxies.

---

### 3.7 NEW ZEALAND

| ID | Series | Source | Frequency | Score Logic |
|----|--------|--------|-----------|------------|
| NZ-ER-1 | NZ GDP Growth | Stats NZ | Quarterly | Proxy for capacity utilization — use output gap estimate |
| NZ-ER-2 | NZ Industrial Production / GDP | Stats NZ / FRED `NZLPROINDQISMEI` | Quarterly | Standard |
| NZ-ER-3 | NZ Unemployment 29m ROC | Stats NZ / FRED `LRUNTTTTNTM156S` | Quarterly | Standard counterintuitive |
| NZ-ER-4 | NZ CPI Fast vs Slow ROC | Stats NZ / FRED `NZLCPIALLQINMEI` | Quarterly | Standard |
| NZ-ER-5 | NZ CPI Level | FRED `NZLCPIALLQINMEI` | Quarterly | Standard thresholds |
| NZ-ER-6 | NZ PPI Inputs 12m ROC | Stats NZ | Quarterly | Sensitive materials proxy |
| NZ-ER-7 | NZ PMI Manufacturing | BusinessNZ / BNZ | Monthly | Inverted scoring |

**Note:** NZ data is heavily quarterly. Use BusinessNZ PMI and ANZ Business Confidence as monthly proxies.

---

## SECTION 4 — TARGET VARIABLES FOR PREDICTIVE RELEVANCE TESTING

The agent should test each indicator series from Sections 1–3 against all of these target variables. The goal is to identify lead times, correlation structure, and Granger causality relationships.

### 4.1 ECONOMIC TARGET VARIABLES (to predict)

| ID | Variable | Series / Source | Notes |
|----|----------|----------------|-------|
| T-EC-1 | US GDP YoY | `GDPC1` FRED (QoQ annualised) | Primary economic activity measure |
| T-EC-2 | EA GDP YoY | Eurostat `namq_10_gdp` | |
| T-EC-3 | Japan GDP YoY | Cabinet Office Japan / FRED | |
| T-EC-4 | UK GDP YoY | ONS / FRED | |
| T-EC-5 | Canada GDP YoY | StatsCan | |
| T-EC-6 | Australia GDP YoY | ABS | |
| T-EC-7 | US Industrial Production | `INDPRO` FRED | Monthly proxy for GDP |
| T-EC-8 | US CPI YoY | `CPIAUCSL` FRED | Inflation target variable |
| T-EC-9 | EA HICP YoY | ECB | Inflation |
| T-EC-10 | Global Manufacturing PMI | JPMorgan/S&P Global composite | Economic cycle |
| T-EC-11 | US Credit Impulse (2nd derivative of credit/GDP) | Derived from Z.1 and FRED `GDP` | Howell's preferred leading indicator |
| T-EC-12 | BIS Credit-to-GDP Gap | BIS Table E1 | Early warning for credit cycle turning points |

---

### 4.2 ASSET CLASS TARGET VARIABLES (to predict — 3, 6, 12 month forward returns)

#### Equities
| ID | Asset | Series / Source | Notes |
|----|-------|----------------|-------|
| T-EQ-1 | US S&P 500 Total Return | Yahoo `^GSPC` / FRED `SP500` | Core equity benchmark |
| T-EQ-2 | MSCI World | Yahoo `URTH` ETF proxy or MSCI data | Global equities |
| T-EQ-3 | MSCI EM | Yahoo `EEM` ETF proxy | EM equity — high sensitivity to dollar and global liquidity |
| T-EQ-4 | Euro Stoxx 50 | Yahoo `^STOXX50E` | European equities |
| T-EQ-5 | Nikkei 225 | Yahoo `^N225` | Japan equities — highly sensitive to yen and BoJ policy |
| T-EQ-6 | ASX 200 | Yahoo `^AXJO` | Australian equities |

#### Fixed Income
| ID | Asset | Series / Source | Notes |
|----|-------|----------------|-------|
| T-FI-1 | US 10Y Treasury Total Return | FRED `DGS10` (yield) / Bloomberg AGG proxy | Duration sensitivity to liquidity |
| T-FI-2 | US HY Spread | `BAMLH0A0HYM2OAS` FRED | Credit risk premium |
| T-FI-3 | US IG Spread | `BAMLC0A0CM` FRED | Investment grade credit |
| T-FI-4 | German 10Y Bund | FRED `IRLTLT01DEM156N` | European safe haven |
| T-FI-5 | Italy−Germany 10Y Spread (BTP-Bund) | Derived: IT10Y − DE10Y | Eurozone stress indicator |
| T-FI-6 | EM Sovereign Spread (EMBI) | JPMorgan EMBI — Yahoo proxy `EMB` ETF | EM credit — dollar sensitivity |

#### FX
| ID | Asset | Series / Source | Notes |
|----|-------|----------------|-------|
| T-FX-1 | DXY Broad USD | `DTWEXBGS` FRED | Primary liquidity FX signal |
| T-FX-2 | EUR/USD | FRED `DEXUSEU` | |
| T-FX-3 | USD/JPY | FRED `DEXJPUS` | Yen carry trade — global risk appetite |
| T-FX-4 | AUD/USD | FRED `DEXUSAL` | Commodity / risk-on proxy |
| T-FX-5 | USD/CNY | FRED `DEXCHUS` | China liquidity transmission |
| T-FX-6 | NZD/USD | FRED `DEXUSNZ` | |

#### Commodities
| ID | Asset | Series / Source | Notes |
|----|-------|----------------|-------|
| T-CM-1 | WTI Crude Oil | FRED `DCOILWTICO` | Energy — global demand signal |
| T-CM-2 | Brent Crude | FRED `DCOILBRENTEU` | |
| T-CM-3 | Gold | FRED `GOLDAMGBD228NLBM` | Safe haven / real rate inverse |
| T-CM-4 | Copper | Yahoo `HG=F` | Industrial demand — "Doctor Copper" |
| T-CM-5 | CRB Index | CRB / Yahoo `^CRB` | Broad commodity basket |
| T-CM-6 | Agricultural Index | S&P GSCI Agri or Yahoo `DJP` | Food inflation signal |

#### Real Estate / Credit Proxies
| ID | Asset | Series / Source | Notes |
|----|-------|----------------|-------|
| T-RE-1 | US Case-Shiller HPI | FRED `CSUSHPINSA` | Housing — key collateral signal |
| T-RE-2 | US REIT Index | Yahoo `VNQ` ETF | Real estate equity proxy |

---

## SECTION 5 — COMPOSITE SCORING AND INDEX CONSTRUCTION

### 5.1 Per-Economy Composite Scores

For each economy, compute three sub-scores:

```
L1_score[country]  = sum of CB signals     (range −4 to +4)
L2a_score[country] = sum of wholesale signals (range −6 to +6, including global signals)
L2b_score[country] = sum of economic reality signals (range −7 to +7)

Total_score[country] = L1 + L2a + L2b    (range −17 to +17)
```

### 5.2 Global Composite

```
Global_liquidity_score = weighted sum of Total_score[country]
  Weights (approximate financial system size):
  US: 0.35 | EA: 0.25 | Japan: 0.15 | UK: 0.10 | Canada: 0.05 | AU: 0.05 | NZ: 0.01 | Residual: 0.04
```

### 5.3 Normalised Z-Score Version (for regression)

For each raw series:
1. Compute 12-month rate of change (or level where appropriate — e.g. spreads, policy rate)
2. Compute rolling Z-score: `Z = (x − mean) / std` over trailing 5-year window
3. Aggregate by equal weight within each layer, then weight layers 40/35/25 (L1/L2a/L2b) into composite

### 5.4 Layer Interaction States

Assign a regime label per economy based on L1/L2a/L2b direction (positive or negative):

| L1 | L2a | L2b | Label |
|----|-----|-----|-------|
| + | + | + | Early cycle — max bullish |
| + | + | − | Late easing — recovery underway |
| + | − | + | Transmission broken — CB easing not transmitting |
| − | + | − | Late cycle — tightening into hot economy |
| − | − | + | Contraction — CB tightening, economy weakening |
| − | − | − | Maximum contraction |

---

## SECTION 6 — DATA PIPELINE NOTES FOR AGENT

### Primary Free APIs
- **FRED API:** `https://api.stlouisfed.org/fred/series/observations?series_id={ID}&api_key={KEY}`
  - Register free at fred.stlouisfed.org for API key
  - Covers majority of US series and many international series
- **BIS:** `https://data.bis.org/api/data/{dataset}/{key}` — see BIS SDMX API docs
- **ECB:** `https://data-api.ecb.europa.eu/service/data/{dataset}/{key}` — SDMX 2.1
- **BoJ:** CSV downloads from `https://www.stat-search.boj.or.jp`
- **RBA:** CSV downloads from `https://www.rba.gov.au/statistics/tables/`
- **RBNZ:** CSV downloads from `https://www.rbnz.govt.nz/statistics`
- **BoE:** API at `https://www.bankofengland.co.uk/boeapps/database/` or direct CSV
- **BoC:** `https://www.bankofcanada.ca/valet/observations/{series}/json`
- **Yahoo Finance:** via `yfinance` Python library for asset prices

### Suggested Fetch Frequency
- **Daily:** All policy rates, overnight spreads (SOFR, EFFR, ESTR, SONIA, TONAR, AONIA, CORRA, NZONIA), yield curves, FX, equity indices, credit spreads, VIX, RRP, DXY
- **Weekly:** FRED H.8 bank credit, MMF assets, commercial paper, Fed balance sheet, primary dealer data
- **Monthly:** CPI, industrial production, unemployment, bank lending surveys, M2/M3 aggregates, RBA/RBNZ/BoJ credit series
- **Quarterly:** Flow of funds (Z.1, BoJ FoF, ECB financial accounts, ABS 5232.0, StatsCan NBSA), BIS tables, capacity utilization, BoC/ECB/BoE lending surveys, Tankan

### Data Gaps and Substitutions
| Gap | Substitution |
|-----|-------------|
| Eurodollar market (unobservable) | Cross-currency basis EUR/USD and JPY/USD |
| Collateral multiplier (not public) | VIX as haircut proxy; NY Fed primary dealer repo / SOFR volume ratio |
| Hedge fund leverage (Form PF — private) | VIX + prime broker credit (not public); use HY spread as proxy |
| NZ quarterly CPI | BusinessNZ PMI input prices as monthly proxy |
| AU quarterly industrial production | Judo Bank PMI manufacturing as monthly proxy |
| Japan YCC-distorted yield curve | Flag as distorted; use BoJ balance sheet ROC as primary CB signal instead |

---

## SECTION 7 — THEORETICAL PRIORS FOR RELEVANCE TESTING

These are the expected lead times and relationships based on Howell's framework. Use as hypotheses to test, not fixed assumptions.

| Indicator Type | Expected Lead to Asset Prices | Expected Lead to Real Economy | Direction |
|---------------|------------------------------|------------------------------|-----------|
| CB balance sheet 12m ROC | 6–12 months | 12–18 months | Positive |
| Net liquidity (WALCL−TGA−RRP) | 3–6 months | 9–15 months | Positive |
| Private bank credit 12m ROC | 3–9 months | 6–12 months | Positive |
| Yield curve steepness | 12–18 months | 18–24 months | Positive (steep = bullish) |
| Cross-currency basis | 1–3 months | 6–9 months | Positive (less negative = bullish) |
| HY credit spread | Coincident to 3 months leading | 3–6 months | Negative (tighter = bullish) |
| DXY (dollar) | 1–6 months | 6–12 months | Negative (weaker dollar = bullish global liquidity) |
| Real policy rate | 6–12 months | 12–18 months | Negative (more negative = bullish) |
| CPI deceleration (L2b-ER-4) | 3–6 months (signals CB will ease) | Lagging | Positive |
| SOFR−EFFR spread | Coincident to 1 month | 1–3 months | Negative (tighter = better) |

### Howell's Core Claim (test this first)
Global liquidity (the composite) leads global equity returns by approximately 6–9 months and global industrial production by approximately 12–18 months. This is the primary hypothesis to validate with your data pipeline.

---

*Framework sources: Michael J. Howell, Capital Wars: The Rise of Global Liquidity (Palgrave Macmillan, 2020); Mark Boucher, The Hedge Fund Edge (Wiley, 1999). Data sources are all publicly available as of 2025–2026.*
