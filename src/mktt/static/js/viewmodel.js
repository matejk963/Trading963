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
    if (typeof Plotly === 'undefined') {
      console.error('viewmodel: Plotly not loaded; cannot render #' + fig.id);
      return;
    }
    Plotly.newPlot(node, fig.traces || [], fig.layout || {}, {
      responsive: true,
      displayModeBar: false,
    });
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
    // exposed for targeted re-render / testing
    _renderFigure: renderFigure,
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
