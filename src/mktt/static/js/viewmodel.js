/*
 * viewmodel.js — the ONE generic ViewModel renderer (spec §5.1, §10).
 *
 * Consumes the envelope every section returns:
 *
 *   ViewModel = {
 *     figures: [ { id, traces:[...], layout:{...} } ],   // -> Plotly.newPlot
 *     tables:  [ { id, columns:[...], rows:[...] } ],     // -> HTML table
 *     meta: {
 *       status:  "ok" | "empty" | "stale" | "error",     // !ok -> banner
 *       message, asof, title, context,
 *       readouts:{ stage, rs_rank, ... }                 // -> badges
 *     }
 *   }
 *
 * Uniform rendering is the whole reason the envelope is standardized — this kills
 * per-page bespoke render JS. Pure DOM + Plotly, no framework.
 *
 * Each element is keyed by `id`; the page template owns matching placeholder divs.
 * Element-target ids (figures/tables) default to `f.id` / `t.id`; meta sinks default
 * to `#vm-status`, `#vm-readouts`, `#vm-title` but are overridable per call.
 *
 * MANUAL CHECK (no JS test runner in the repo — jsdom not installed; the Python
 * suite asserts the *envelope shape* this renderer consumes, see tests/test_viewmodel.py):
 *   1. Load a page that `{% include "_viewmodel_shell.html" %}` with a route returning
 *      a vm() envelope.
 *   2. status:"ok"  -> no banner; status:"empty"/"stale"/"error" -> banner shows.
 *   3. figures[]    -> Plotly chart renders in #<figure.id>.
 *   4. tables[]     -> HTML <table.vm-table> built into #<table.id>.
 *   5. meta.readouts-> one .vm-badge per key in #vm-readouts.
 */
(function (global) {
  'use strict';

  function el(id) {
    if (typeof id !== 'string') return id;
    if (typeof document === 'undefined') return null;
    return document.getElementById(id);
  }

  function clear(node) {
    if (node) node.innerHTML = '';
  }

  // --- figures ------------------------------------------------------------ //
  function renderFigure(fig) {
    var node = el(fig.id);
    if (!node) {
      console.warn('viewmodel: no element #' + fig.id + ' for figure');
      return;
    }
    // OHLC figures (kind:"ohlc") render via TradingView Lightweight Charts —
    // route BEFORE Plotly (the LWC figure carries no `traces`). adr/0003.
    if (fig.kind === 'ohlc') {
      renderOhlcFigure(fig, node);
      return;
    }
    // Indicators pane (kind:"indicators") — a second Lightweight-Charts sub-chart
    // stacked under the price and time-synced with it (Slice 6). adr/0003.
    if (fig.kind === 'indicators') {
      renderIndicatorPane(fig, node);
      return;
    }
    if (typeof Plotly === 'undefined') {
      console.error('viewmodel: Plotly not loaded; cannot render #' + fig.id);
      return;
    }
    Plotly.newPlot(node, fig.traces || [], fig.layout || {}, {
      responsive: true,
      displayModeBar: false,
    });
  }

  // --- OHLC figures (Lightweight Charts) ---------------------------------- //
  // line colours for the MA overlay series, by period (falls back to gray).
  var OHLC_MA_COLORS = { 50: '#2962FF', 150: '#FF6D00', 200: '#AA00FF' };
  var RS_COLOR = '#FFD600';
  var RS_PRICE_SCALE = 'rs-scale';  // RS overlay lives on its own (overlay) scale.

  // The price LWC chart, stashed so the indicators pane (Slice 6) can sync to
  // it. Re-set on every price render; cleared on dispose.
  var _priceChart = null;

  // Per-indicator client scale config (Slice 6). `name` matches data-ind on the
  // .ind-tog checkboxes; `scale` is the priceScaleId; `scaleMargins` keeps the
  // bands from colliding when several are shown at once.
  var IND_STYLE = {
    'RS Rank':      { color: '#29B6F6', scaleMargins: { top: 0.05, bottom: 0.55 } },
    'Mansfield RS': { color: '#FFD600', scaleMargins: { top: 0.40, bottom: 0.25 } },
    'Stage':        { color: '#AB47BC', scaleMargins: { top: 0.70, bottom: 0.02 } },
  };

  // Normalize a bar time to a "YYYY-MM-DD" string. Accepts a string (passthrough),
  // a number (epoch seconds, as LWC may emit), or a LWC BusinessDay object
  // {year,month,day}. Defensive: LWC's setData mutates the `time` field of the
  // data objects in place, so a stale figure can carry a non-string time on a
  // re-render (Slice 3 / #10 — see RS-toggle blank-chart bug).
  function toYmd(t) {
    if (typeof t === 'string') return t;
    if (t && typeof t === 'object' && t.year != null) {
      var mo = t.month < 10 ? '0' + t.month : '' + t.month;
      var da = t.day < 10 ? '0' + t.day : '' + t.day;
      return t.year + '-' + mo + '-' + da;
    }
    if (typeof t === 'number') {
      // LWC stores BusinessDay times as a UTC epoch (seconds).
      var d = new Date(t * 1000);
      var m2 = d.getUTCMonth() + 1;
      var dd2 = d.getUTCDate();
      return d.getUTCFullYear() + '-' +
        (m2 < 10 ? '0' + m2 : m2) + '-' + (dd2 < 10 ? '0' + dd2 : dd2);
    }
    return String(t);
  }

  // ISO week key (YYYY-Www) for a "YYYY-MM-DD" string — groups daily bars into
  // weekly buckets (Slice 3 / #10, client-side aggregation; LWC v3.8 has none).
  function isoWeekKey(ymd) {
    var parts = toYmd(ymd).split('-');
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    // ISO: Thursday of the current week decides the year.
    var day = (d.getUTCDay() + 6) % 7;  // Mon=0..Sun=6
    d.setUTCDate(d.getUTCDate() - day + 3);
    var firstThu = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
    var fday = (firstThu.getUTCDay() + 6) % 7;
    firstThu.setUTCDate(firstThu.getUTCDate() - fday + 3);
    var week = 1 + Math.round((d - firstThu) / (7 * 24 * 3600 * 1000));
    return d.getUTCFullYear() + '-W' + (week < 10 ? '0' + week : week);
  }

  // Aggregate daily bars [{time,open,high,low,close}] + volume [{time,value}] +
  // benchmark [{time,value}] to the displayed timeframe ("D"|"W"|"M").
  // OHLC rules: open=first, high=max, low=min, close=last, volume=sum. The bucket
  // time is the LAST day in the bucket (so candles sit on the period close).
  function aggregate(bars, volume, benchmark, tf) {
    if (tf === 'D' || !bars || !bars.length) {
      // Clone so we NEVER return the stashed fig arrays by reference — LWC's
      // setData mutates data objects in place, which would otherwise corrupt
      // node._ohlcFig across re-renders (Slice 3 / #10).
      return {
        bars: (bars || []).map(function (b) {
          return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close };
        }),
        volume: (volume || []).map(function (v) { return { time: v.time, value: v.value }; }),
        benchmark: (benchmark || []).map(function (b) { return { time: b.time, value: b.value }; }),
      };
    }
    var volByTime = {};
    (volume || []).forEach(function (v) { volByTime[v.time] = v.value; });
    var benchByTime = {};
    (benchmark || []).forEach(function (b) { benchByTime[b.time] = b.value; });

    var keyFn = tf === 'W'
      ? isoWeekKey
      : function (ymd) { return toYmd(ymd).slice(0, 7); };  // calendar month YYYY-MM

    var order = [];
    var buckets = {};
    bars.forEach(function (bar) {
      var k = keyFn(bar.time);
      var b = buckets[k];
      if (!b) {
        b = buckets[k] = {
          time: bar.time, open: bar.open, high: bar.high, low: bar.low,
          close: bar.close, volume: 0, bench: null,
        };
        order.push(k);
      }
      // first bar already set open; update high/low/close/time to the latest.
      if (bar.high != null && (b.high == null || bar.high > b.high)) b.high = bar.high;
      if (bar.low != null && (b.low == null || bar.low < b.low)) b.low = bar.low;
      b.close = bar.close;
      b.time = bar.time;  // last day in the bucket
      var vv = volByTime[bar.time];
      if (vv != null) b.volume += vv;
      var bv = benchByTime[bar.time];
      if (bv != null) b.bench = bv;  // last benchmark close in the bucket
    });

    var outBars = [], outVol = [], outBench = [];
    order.forEach(function (k) {
      var b = buckets[k];
      outBars.push({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
      outVol.push({ time: b.time, value: b.volume });
      outBench.push({ time: b.time, value: b.bench });
    });
    return { bars: outBars, volume: outVol, benchmark: outBench };
  }

  // Aggregate a daily LINE series [{time,value}] to the displayed timeframe
  // ("D"|"W"|"M") using the SAME bucket keys as `aggregate` (isoWeekKey for W,
  // YYYY-MM for M) and taking the LAST value in each bucket. The indicator
  // series (RS Rank / Mansfield RS / Stage) are slow / period-end / categorical,
  // so last-in-bucket is the correct downsample and keeps the indicator pane's
  // bar count equal to the price's — required for the logical-range sync to stay
  // aligned at W and M. Bucket time = the last day in the bucket (matches `aggregate`).
  function aggregateLine(points, tf) {
    if (tf === 'D' || !points || !points.length) {
      return (points || []).map(function (p) { return { time: p.time, value: p.value }; });
    }
    var keyFn = tf === 'W'
      ? isoWeekKey
      : function (ymd) { return toYmd(ymd).slice(0, 7); };  // calendar month YYYY-MM
    var order = [];
    var buckets = {};
    points.forEach(function (p) {
      var k = keyFn(p.time);
      if (!buckets[k]) { buckets[k] = { time: p.time, value: p.value }; order.push(k); }
      else { buckets[k].time = p.time; buckets[k].value = p.value; }  // last in bucket
    });
    return order.map(function (k) { return { time: buckets[k].time, value: buckets[k].value }; });
  }

  // Resample a daily LINE series [{time,value}] onto an EXACT target grid of
  // "YYYY-MM-DD" strings (the price chart's displayed bar times). For each target
  // time T we take the series' most-recent value AT-OR-BEFORE T (as-of /
  // forward-fill); null before the first available point. The result's time array
  // EXACTLY equals `displayedTimes` (same count, same order), so under the
  // logical-range (bar-index) sync the same bar index is the same date on both
  // panes — perfect alignment with free-scroll. Both inputs are assumed sorted
  // ascending by date (server emits sorted series; price bars are date-ordered).
  function alignLineToTimes(points, displayedTimes) {
    var pts = (points || []).map(function (p) { return { time: toYmd(p.time), value: p.value }; });
    var out = [];
    var j = 0;            // walk pointer into pts (monotonic, since both sorted)
    var last = null;      // most-recent value at-or-before the current target
    for (var i = 0; i < displayedTimes.length; i++) {
      var t = displayedTimes[i];
      while (j < pts.length && pts[j].time <= t) { last = pts[j].value; j++; }
      out.push({ time: t, value: last });
    }
    return out;
  }

  // SMA(period) over an array of bars (on the displayed timeframe) -> {time,value}
  // points (null in the warm-up window).
  function smaSeries(bars, period) {
    var out = [], sum = 0, win = [];
    for (var i = 0; i < bars.length; i++) {
      var c = bars[i].close;
      win.push(c);
      sum += (c == null ? 0 : c);
      if (win.length > period) sum -= (win.shift() || 0);
      var ready = win.length === period && win.every(function (v) { return v != null; });
      out.push({ time: bars[i].time, value: ready ? sum / period : null });
    }
    return out;
  }

  // Mansfield Relative Strength on the displayed timeframe: RP = close/bench,
  // normalized to its trailing SMA (window = min(52, len)). value = (RP/SMA - 1)*100.
  function mansfieldRs(bars, benchmark) {
    var benchByTime = {};
    (benchmark || []).forEach(function (b) { benchByTime[b.time] = b.value; });
    var rp = bars.map(function (bar) {
      var bv = benchByTime[bar.time];
      return (bar.close != null && bv != null && bv !== 0) ? bar.close / bv : null;
    });
    var win = Math.min(52, rp.length) || 1;
    var out = [];
    for (var i = 0; i < rp.length; i++) {
      var lo = Math.max(0, i - win + 1);
      var sum = 0, n = 0;
      for (var j = lo; j <= i; j++) { if (rp[j] != null) { sum += rp[j]; n++; } }
      var avg = n ? sum / n : null;
      out.push({
        time: bars[i].time,
        value: (rp[i] != null && avg != null && avg !== 0) ? (rp[i] / avg - 1) * 100 : null,
      });
    }
    return out;
  }

  // --- crosshair sync (native, v4) — Slice 6 ------------------------------ //
  // lightweight-charts@4.x exposes chart.setCrosshairPosition(price, time, series)
  // and chart.clearCrosshairPosition(), so we drive the PARTNER chart's REAL
  // crosshair (a true synced vertical time-line) instead of the v3.8 guide-div
  // hack. The price arg is required by the API but only the time matters for the
  // vertical line, so we pass an arbitrary value drawn on a stable partner series.

  // Subscribe `sourceChart`'s crosshair to drive the PARTNER chart's native
  // crosshair. The partner chart + a stable series are looked up DYNAMICALLY each
  // move (the indicator chart is rebuilt on every toggle / symbol switch, so
  // capturing them would go stale) via the supplied resolver -> { chart, series }
  // | null. On leave (param.time == null) the partner's crosshair is cleared.
  function syncCrosshairFrom(sourceChart, resolvePartner) {
    if (!sourceChart) return;
    sourceChart.subscribeCrosshairMove(function (param) {
      var partner = resolvePartner();
      if (!partner || !partner.chart || !partner.series) return;
      if (!param || param.time == null) {
        try { partner.chart.clearCrosshairPosition(); } catch (e) { /* noop */ }
        return;
      }
      // The vertical time-line is what matters; the price value is arbitrary.
      try { partner.chart.setCrosshairPosition(0, param.time, partner.series); }
      catch (e) { /* time out of partner range — leave crosshair as-is */ }
    });
  }

  // Clear the partner chart's crosshair (used when the indicator pane is hidden).
  function clearCrosshair(chart) {
    if (chart) { try { chart.clearCrosshairPosition(); } catch (e) { /* noop */ } }
  }

  // Read the technical toolkit state from the DOM (timeframe, MA toggles, RS).
  function readToolkitState() {
    var tf = 'D';
    if (typeof document !== 'undefined') {
      var active = document.querySelector('.tech-tf.tech-tf-active');
      if (active) tf = active.getAttribute('data-tf') || 'D';
    }
    var mas = [];
    var rs = false;
    if (typeof document !== 'undefined') {
      Array.prototype.forEach.call(document.querySelectorAll('.tech-ma'), function (cb) {
        if (cb.checked) mas.push(+cb.getAttribute('data-ma'));
      });
      var rsCb = document.getElementById('tech-rs');
      rs = !!(rsCb && rsCb.checked);
    } else {
      mas = [50, 150, 200];
    }
    return { tf: tf, mas: mas, rs: rs };
  }

  function renderOhlcFigure(fig, node) {
    if (typeof LightweightCharts === 'undefined') {
      console.error('viewmodel: LightweightCharts not loaded; cannot render #' + fig.id);
      return;
    }
    // Stash the raw (daily) figure so a toolkit change re-aggregates/recomputes
    // WITHOUT refetching (Slice 3 / #10).
    node._ohlcFig = fig;

    // Dispose the prior chart stashed on the node before recreating — else
    // re-selecting symbols (or toggling the toolkit) leaks/stacks chart instances.
    if (node._lwcChart) {
      try { node._lwcChart.remove(); } catch (e) { /* already removed */ }
      node._lwcChart = null;
      if (_priceChart) _priceChart = null;
    }
    node.innerHTML = '';

    var state = readToolkitState();
    var agg = aggregate(fig.bars || [], fig.volume || [], fig.benchmark || [], state.tf);

    // Stash the EXACT displayed bar times (as "YYYY-MM-DD" strings) on the price
    // host so the indicator pane can resample its series onto this identical grid
    // (same count, same times) — required for the logical-range (bar-index) sync
    // to align dates 1:1 across panes. Refreshed on every price render / D-W-M
    // re-aggregation, BEFORE the indicator pane re-renders below.
    node._displayedTimes = agg.bars.map(function (b) { return toYmd(b.time); });

    var chart = LightweightCharts.createChart(node, {
      width: node.clientWidth,
      height: node.clientHeight || 480,
      layout: {
        background: { type: LightweightCharts.ColorType.Solid, color: 'transparent' },
        textColor: '#999',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.15)' },
      // rightOffset: breathing room past the last bar so it isn't glued to the
      // edge (and whitespace to scroll into). The indicators pane below MUST use the
      // same value so equal logical ranges align bar-for-bar.
      timeScale: { borderColor: 'rgba(255,255,255,0.15)', rightOffset: 56 },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      // Mouse WHEEL zooms the time axis (user asked to zoom by scrolling). Wheel-pan
      // stays off so the chart zooms (not slides) on wheel; drag-pan + pinch + axis
      // drag remain on.
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
    });
    node._lwcChart = chart;
    // Stash the price chart so the indicators pane (Slice 6) time-syncs to it.
    _priceChart = chart;

    var candles = chart.addCandlestickSeries({
      upColor: '#26a69a', downColor: '#ef5350',
      borderUpColor: '#26a69a', borderDownColor: '#ef5350',
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    // LWC's setData normalizes the `time` field of the data objects IN PLACE
    // (string "YYYY-MM-DD" -> internal repr). The Daily branch of aggregate()
    // returns fig.bars BY REFERENCE, and we stash fig on node._ohlcFig — so we
    // must hand setData FRESH plain objects, or the stash gets corrupted and the
    // next re-aggregation (e.g. RS toggle on weekly) crashes (Slice 3 / #10).
    candles.setData(agg.bars.map(function (b) {
      return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close };
    }));
    // Stash the candle series so the indicator pane's crosshair sync has a stable
    // partner series to drive this chart's native crosshair (Slice 6, v4).
    node._lwcSeries = candles;

    // MA overlay lines — recomputed on the DISPLAYED timeframe (so they stay
    // correct after aggregation), one per toggled period.
    state.mas.forEach(function (period) {
      var line = chart.addLineSeries({
        color: OHLC_MA_COLORS[period] || '#888',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(smaSeries(agg.bars, period).filter(function (p) { return p.value !== null && p.value !== undefined; }));
    });

    // Mansfield RS overlay on its OWN (overlay) price scale — recomputed on the
    // displayed timeframe from symbol-close / benchmark-close.
    if (state.rs) {
      var rsLine = chart.addLineSeries({
        color: RS_COLOR,
        lineWidth: 1,
        priceScaleId: RS_PRICE_SCALE,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      rsLine.setData(mansfieldRs(agg.bars, agg.benchmark).filter(function (p) { return p.value !== null && p.value !== undefined; }));
      try {
        chart.priceScale(RS_PRICE_SCALE).applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      } catch (e) { /* older LWC — overlay scale auto-sizes */ }
    }

    // Default view = the last ~1 year (timeframe-aware), with the right margin past
    // the last bar; the user wheel-zooms out to see more history. setVisibleLogicalRange
    // (instead of fitContent, which showed all ~6y) runs BEFORE the indicators pane is
    // (re)built below, so the pane adopts THIS range and both panes line up on last-year.
    var _nbars = agg.bars.length;
    var _viewBars = ({ D: 252, W: 52, M: 12 })[state.tf] || 252;  // ~1 year by timeframe
    if (_nbars > 0) {
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, _nbars - _viewBars),
        to: _nbars - 1 + 56,   // +56 == rightOffset: keep the margin visible
      });
    } else {
      chart.timeScale().fitContent();
    }

    // The price chart was just rebuilt (new instance) — re-sync the indicators
    // pane to it so pan/zoom stays linked after a symbol switch or D/W/M change
    // (Slice 6). Guarded if the pane was never built.
    var indNode = el('monitor_history');
    if (indNode && indNode._indFig) renderIndicatorPane(indNode._indFig, indNode);

    // crosshair readout — write O/H/L/C + date for the hovered bar.
    var readout = el('monitor-ohlc-readout');
    if (readout) {
      chart.subscribeCrosshairMove(function (param) {
        if (!param || !param.time || !param.seriesData) return;
        var bar = param.seriesData.get(candles);
        if (!bar) return;
        var fmt = function (v) { return (v === undefined || v === null) ? '—' : (+v).toFixed(2); };
        readout.textContent =
          param.time + '  O ' + fmt(bar.open) + '  H ' + fmt(bar.high) +
          '  L ' + fmt(bar.low) + '  C ' + fmt(bar.close);
      });
    }

    // Crosshair sync price -> indicator pane: resolve the CURRENT indicator chart
    // + its stable series dynamically each move (the indicator pane is rebuilt on
    // toggle / symbol switch, so we must never capture a stale instance). One
    // subscription per price render (the price chart is the single, persistent
    // source). v4 native: drives the partner's real crosshair.
    syncCrosshairFrom(chart, function () {
      var ind = el('monitor_history');
      if (!ind || !ind._indChart || !ind._indSeries || ind.style.display === 'none') return null;
      return { chart: ind._indChart, series: ind._indSeries };
    });
  }

  // Re-render the stashed OHLC figure on #monitor_price (toolkit change → no refetch).
  function rerenderOhlc() {
    var node = el('monitor_price');
    if (node && node._ohlcFig) renderOhlcFigure(node._ohlcFig, node);
  }

  // --- Indicators pane (Lightweight Charts, synced) — Slice 6 ------------- //
  // Read the .ind-tog checkbox state -> { name: bool } (which indicators are on).
  function readIndicatorState() {
    var on = {};
    if (typeof document === 'undefined') return on;
    Array.prototype.forEach.call(document.querySelectorAll('.ind-tog'), function (cb) {
      on[cb.getAttribute('data-ind')] = cb.checked;
    });
    return on;
  }

  // Bidirectional sync between two LWC charts by VISIBLE LOGICAL RANGE (bar
  // index, not time). Logical range can represent empty space PAST the last bar
  // (from/to are fractional bar indices that run beyond [0, len-1]), so the
  // master can free-scroll into whitespace and the partner follows — whereas a
  // TIME range clamps back to the last bar and pins the chart to its right edge.
  // Bar cadence is matched (indicators aggregate to the same D/W/M timeframe as
  // the price), so equal logical indices line up at every timeframe.
  //
  // Guardless bidirectional mirror — the canonical TradingView multi-chart sync.
  // No `_syncOwner` flag: setting a chart's logical range to the value it already
  // holds does NOT re-fire its subscription, so the echo (a→b→a) terminates on its
  // own. A stateful guard here was the bug — it could get stuck non-null in some
  // interleavings and then silently block ALL subsequent syncs (flaky desync).
  function linkLogicalRanges(a, b) {
    if (!a || !b) return;
    a.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (range) { try { b.timeScale().setVisibleLogicalRange({ from: range.from, to: range.to }); } catch (e) { /* out of bounds */ } }
    });
    b.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (range) { try { a.timeScale().setVisibleLogicalRange({ from: range.from, to: range.to }); } catch (e) { /* out of bounds */ } }
    });
  }

  // Render the indicators pane (RS Rank / Mansfield RS / Stage) as a second LWC
  // chart stacked under the price, one line series per CHECKED indicator on its
  // own price scale, time-synced with `_priceChart`. Hidden when none are checked.
  function renderIndicatorPane(fig, node) {
    if (!node) return;
    node._indFig = fig;  // stash for toggle re-render (rerenderIndicators).

    // Dispose any prior pane chart before recreating — else toggling leaks charts.
    if (node._indChart) {
      try { node._indChart.remove(); } catch (e) { /* already removed */ }
      node._indChart = null;
      node._indSeries = null;
    }
    node.innerHTML = '';

    var state = readIndicatorState();
    var series = (fig.series || []).filter(function (s) { return state[s.name] !== false; });
    // No checkbox checked -> hide the pane entirely (Slice 6). Also clear the
    // price chart's crosshair (the indicator pane that drove it is gone).
    var anyOn = series.length > 0;
    if (!anyOn) {
      clearCrosshair(_priceChart);
      node.style.display = 'none';
      return;
    }
    node.style.display = '';

    if (typeof LightweightCharts === 'undefined') {
      console.error('viewmodel: LightweightCharts not loaded; cannot render #' + fig.id);
      return;
    }

    var chart = LightweightCharts.createChart(node, {
      width: node.clientWidth,
      height: node.clientHeight || 320,
      layout: {
        background: { type: LightweightCharts.ColorType.Solid, color: 'transparent' },
        textColor: '#999',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.15)' },
      // Match the price chart's rightOffset so equal logical ranges align.
      timeScale: { borderColor: 'rgba(255,255,255,0.15)', rightOffset: 56 },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      // Match the price chart: wheel zooms (and syncs to price via logical range).
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
    });
    node._indChart = chart;

    // Align each (daily) indicator series onto the price chart's EXACT displayed
    // bar grid (`_displayedTimes`), so both panes share an identical time axis
    // (same count, same times) and equal logical indices are the same date —
    // perfect alignment under the logical-range (bar-index) sync, at every
    // timeframe (D/W/M). The price stashes `_displayedTimes` on each render BEFORE
    // re-rendering this pane. Fallback: if it's missing (pane somehow renders
    // before the price), aggregate independently to the toolkit timeframe so
    // nothing breaks (the old, ~13px-misaligned path).
    var priceNode = el('monitor_price');
    var displayedTimes = priceNode && priceNode._displayedTimes;
    var tf = readToolkitState().tf;

    series.forEach(function (s, idx) {
      var style = IND_STYLE[s.name] || {};
      var scaleId = s.scale || s.name;
      var line = chart.addLineSeries({
        color: style.color || '#888',
        lineWidth: 1,
        priceScaleId: scaleId,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      // Stash the first series as the stable partner for crosshair sync (Slice 6,
      // v4): the price chart drives THIS chart's native crosshair through it.
      if (idx === 0) node._indSeries = line;
      if (displayedTimes && displayedTimes.length) {
        // ALIGNED path: emit the FULL displayed grid so the indicator chart's
        // time scale has the IDENTICAL set/count of bars as the price (else a
        // leading-null gap would shift index 0 and re-break the bar-index sync).
        // Null slots become LWC "whitespace" points ({time} only) — they
        // occupy the time-scale slot but draw nothing, so the line still gaps.
        line.setData(alignLineToTimes(s.data || [], displayedTimes).map(function (p) {
          return (p.value === null || p.value === undefined)
            ? { time: p.time }
            : { time: p.time, value: p.value };
        }));
      } else {
        // FALLBACK path (price grid unavailable): old independent aggregation.
        line.setData(aggregateLine(s.data || [], tf)
          .filter(function (p) { return p.value !== null && p.value !== undefined; })
          .map(function (p) { return { time: p.time, value: p.value }; }));
      }
      if (style.scaleMargins) {
        try { chart.priceScale(scaleId).applyOptions({ scaleMargins: style.scaleMargins }); }
        catch (e) { /* older LWC — scale auto-sizes */ }
      }
    });

    // Logical-range sync with the price chart. If the price chart already has a
    // visible logical range, adopt it (so the pane lines up immediately, incl.
    // any right-edge whitespace); otherwise fit our own content on first build.
    if (_priceChart) {
      var pr = null;
      try { pr = _priceChart.timeScale().getVisibleLogicalRange(); } catch (e) { pr = null; }
      if (pr) {
        // adopt the price's current range so the pane lines up immediately; this
        // runs BEFORE linkLogicalRanges subscribes, so it raises no echo.
        try { chart.timeScale().setVisibleLogicalRange({ from: pr.from, to: pr.to }); }
        catch (e) { chart.timeScale().fitContent(); }
      } else {
        chart.timeScale().fitContent();
      }
      linkLogicalRanges(_priceChart, chart);
    } else {
      chart.timeScale().fitContent();
    }

    // Crosshair sync indicator pane -> price chart: subscribed per indicator
    // render (this chart is a fresh instance each toggle). The price chart + its
    // stable candle series are resolved dynamically so a symbol switch / D/W/M
    // re-render is always honoured. v4 native: drives the price's real crosshair.
    syncCrosshairFrom(chart, function () {
      var price = el('monitor_price');
      if (!price || !price._lwcChart || !price._lwcSeries) return null;
      return { chart: price._lwcChart, series: price._lwcSeries };
    });
  }

  // Re-render the indicators pane from the stashed figure (toggle change → no
  // refetch). Guarded if the pane was never built for this symbol.
  function rerenderIndicators() {
    var node = el('monitor_history');
    if (node && node._indFig) renderIndicatorPane(node._indFig, node);
  }

  // Wire the technical toolkit controls once (D/W/M segmented, MA checkboxes, RS).
  // Idempotent — guarded so repeated calls don't double-bind.
  function wireTechToolkit() {
    if (typeof document === 'undefined') return;
    var toolkit = document.getElementById('monitor-tech-toolkit');
    if (!toolkit || toolkit._wired) return;
    toolkit._wired = true;

    var tfs = toolkit.querySelectorAll('.tech-tf');
    function setActiveTf(btn) {
      Array.prototype.forEach.call(tfs, function (b) {
        var on = b === btn;
        b.classList.toggle('tech-tf-active', on);
        b.style.background = on ? 'var(--bg-card,#1a1a2a)' : 'none';
        b.style.color = on ? 'var(--text,#ccc)' : 'var(--text-dim,#888)';
      });
    }
    // A D/W/M change re-aggregates the price AND the indicator pane to the new
    // timeframe (rerenderOhlc rebuilds the price chart, which re-renders the
    // pane from its stash; the explicit rerenderIndicators() guarantees the pane
    // re-aggregates even if the price chart isn't present yet).
    function onTfChange(btn) { setActiveTf(btn); rerenderOhlc(); rerenderIndicators(); }
    Array.prototype.forEach.call(tfs, function (btn) {
      if (btn.getAttribute('data-tf') === 'D') btn.classList.add('tech-tf-active');
      btn.addEventListener('click', function () { onTfChange(btn); });
    });
    Array.prototype.forEach.call(toolkit.querySelectorAll('.tech-ma'), function (cb) {
      cb.addEventListener('change', rerenderOhlc);
    });
    var rsCb = document.getElementById('tech-rs');
    if (rsCb) rsCb.addEventListener('change', rerenderOhlc);
  }

  // --- tables ------------------------------------------------------------- //
  function renderTable(tbl) {
    var node = el(tbl.id);
    if (!node) {
      console.warn('viewmodel: no element #' + tbl.id + ' for table');
      return;
    }
    var columns = tbl.columns || [];
    var rows = tbl.rows || [];

    var table = document.createElement('table');
    table.className = 'vm-table';

    var thead = document.createElement('thead');
    var htr = document.createElement('tr');
    columns.forEach(function (col) {
      var th = document.createElement('th');
      th.textContent = col;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      // rows may be arrays (positional) or objects (column-keyed).
      var cells = Array.isArray(row)
        ? row
        : columns.map(function (c) { return row[c]; });
      cells.forEach(function (cell) {
        var td = document.createElement('td');
        td.textContent = cell === null || cell === undefined ? '' : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    clear(node);
    node.appendChild(table);
  }

  // --- readouts (badges) -------------------------------------------------- //
  function renderReadouts(readouts, target) {
    var node = el(target || 'vm-readouts');
    if (!node) return;
    clear(node);
    Object.keys(readouts || {}).forEach(function (key) {
      var value = readouts[key];
      var badge = document.createElement('span');
      badge.className = 'vm-badge vm-badge-' + key;
      var label = document.createElement('span');
      label.className = 'vm-badge-label';
      label.textContent = key;
      var val = document.createElement('span');
      val.className = 'vm-badge-value';
      val.textContent = value === null || value === undefined ? '—' : String(value);
      badge.appendChild(label);
      badge.appendChild(val);
      node.appendChild(badge);
    });
  }

  // --- status banner ------------------------------------------------------ //
  function renderStatus(meta, target) {
    var node = el(target || 'vm-status');
    if (!node) return;
    var status = (meta && meta.status) || 'ok';
    if (status === 'ok') {
      clear(node);
      node.style.display = 'none';
      return;
    }
    node.style.display = '';
    node.className = 'vm-banner vm-banner-' + status;
    var msg = (meta && meta.message) ||
      (status === 'empty' ? 'No results.'
        : status === 'stale' ? 'Showing stale data.'
        : 'Something went wrong.');
    if (status === 'stale' && meta && meta.asof) {
      msg += ' (as of ' + meta.asof + ')';
    }
    node.textContent = msg;
  }

  // --- title -------------------------------------------------------------- //
  function renderTitle(meta, target) {
    var node = el(target || 'vm-title');
    if (!node || !meta || !meta.title) return;
    node.textContent = meta.title;
  }

  /**
   * renderViewModel(vm, opts?) — render every element type in one pass.
   *
   * opts (all optional): { statusId, readoutsId, titleId } override the meta
   * sink ids. Returns the vm for chaining.
   */
  function renderViewModel(vm, opts) {
    if (!vm) return vm;
    opts = opts || {};
    var meta = vm.meta || {};

    renderStatus(meta, opts.statusId);
    renderTitle(meta, opts.titleId);
    renderReadouts(meta.readouts || {}, opts.readoutsId);

    (vm.figures || []).forEach(renderFigure);
    (vm.tables || []).forEach(renderTable);

    return vm;
  }

  /**
   * fetchAndRender(url, fetchOpts?, renderOpts?) — the thin-blueprint pattern:
   * GET/POST the section API, then hand the envelope to renderViewModel.
   */
  function fetchAndRender(url, fetchOpts, renderOpts) {
    return fetch(url, fetchOpts)
      .then(function (r) { return r.json(); })
      .then(function (vm) { return renderViewModel(vm, renderOpts); })
      .catch(function (err) {
        console.error('viewmodel: fetch/render failed', err);
        renderStatus(
          { status: 'error', message: 'Failed to load: ' + err },
          renderOpts && renderOpts.statusId
        );
      });
  }

  var api = {
    renderViewModel: renderViewModel,
    fetchAndRender: fetchAndRender,
    // technical toolkit (Slice 3 / #10)
    wireTechToolkit: wireTechToolkit,
    rerenderOhlc: rerenderOhlc,
    // indicators pane (Slice 6) — re-render from the stash on a toggle change.
    rerenderIndicators: rerenderIndicators,
    // exposed for targeted re-render / testing
    _renderFigure: renderFigure,
    _renderOhlcFigure: renderOhlcFigure,
    _renderIndicatorPane: renderIndicatorPane,
    _aggregateOhlc: aggregate,
    _aggregateLine: aggregateLine,
    _alignLineToTimes: alignLineToTimes,
    _smaSeries: smaSeries,
    _mansfieldRs: mansfieldRs,
    _isoWeekKey: isoWeekKey,
    _toYmd: toYmd,
    _renderTable: renderTable,
    _renderReadouts: renderReadouts,
    _renderStatus: renderStatus,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  global.renderViewModel = renderViewModel;
  global.ViewModel = api;
})(typeof window !== 'undefined' ? window : this);
