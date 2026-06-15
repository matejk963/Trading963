# ADR 0003 — Mixed charting: Lightweight Charts for OHLC, Plotly for analytical figures

Status: Accepted (2026-06-13)
Effort: docs/work/2026-06-13-monitor-section
Refines: docs/adr/0002 §2 ("client-render charts via Plotly")
Source: /grill-me on the Monitor PRD (this conversation); decision confirmed in-session at plan time.

## Context
The Monitor section's **technical pane** wants a TradingView-like daily candlestick chart with
D/W/M timeframes, toggleable moving averages, a Mansfield RS line, and a crosshair readout.
adr/0002 §2 established that chart figures are **client-rendered with Plotly** via the generic
`renderViewModel`. Plotly can draw candlesticks, but it is not built for the interaction model of a
price chart (pan/zoom across many bars, fast crosshair, timeframe re-aggregation) and reproducing a
clean TradingView-style technical pane in Plotly is heavier and lower-fidelity than the purpose-built
library. The **fundamental pane** (2×2 EPS/Sales/PE/PS line grid) is a classic analytical figure that
Plotly handles well and that already fits the `renderViewModel` path.

## Decision
1. **Use TradingView Lightweight Charts (MIT) for the OHLC technical pane only.** Daily candlesticks,
   D/W/M (weekly/monthly aggregated from daily bars client-side), MA + RS overlays, crosshair.
2. **Keep Plotly for every analytical figure**, including the Monitor's fundamental 2×2 grid and all
   other sections' charts. No other section adopts Lightweight Charts in this effort.
3. **This is a scoped deviation from adr/0002 §2**, not a reversal: adr/0002's "client-render charts
   via Plotly" now reads **"client-render analytical charts via Plotly; OHLC price charts via
   Lightweight Charts."** The ViewModel envelope and DI/manager contracts are unchanged — the technical
   pane still receives its data as part of the section's ViewModel; only the client renderer differs.

## Consequences
- One new frontend dependency (Lightweight Charts, MIT) vendored/loaded for the Monitor technical pane.
- Two client chart renderers coexist: `renderViewModel` (Plotly, analytical) and a Lightweight-Charts
  renderer (price). The seam is by figure type, not by section.
- W/M aggregation and MA/RS recomputation on the displayed timeframe happen client-side from daily bars.

## Alternatives rejected
- **Pure Plotly candlesticks** (honor adr/0002 strictly) — rejected: heavier, less TradingView-like
  interaction, more work to reach the same fidelity for the core use of the Monitor.
- **Lightweight Charts everywhere** — rejected: it is a price-chart library, not a general plotting
  library; the fundamental/analytical figures are a poor fit and Plotly already serves them well.
