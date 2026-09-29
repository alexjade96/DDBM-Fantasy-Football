// Shared client-side table sort for #panel tables. Loaded by index.html (the
// loaded-league dashboard) and home.html (the landing page's ADP compare
// table). One copy so the two don't drift.
//
// Click a column header to sort. Cells rank by their first embedded number when
// the column has one ("#3 of 10" -> 3, "9-8" -> 9, "+41.4" -> 41.4), else
// alphabetically -- so ranks, records, scores and names all sort without
// per-table config. Opt out with class="nosort" (a grid, not a ranking). A
// cell's data-sort overrides both the numeric heuristic and the compared text.
(function (global) {
  function sortValue(td) {
    var t = (td.textContent || '').trim().replace(/,/g, '');
    var m = t.match(/-?\d+(\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }
  function textValue(td) {
    return (td.dataset && td.dataset.sort !== undefined) ? td.dataset.sort
      : (td.textContent || '').trim();
  }
  // Fantasy position order, not alphabetical. Any column headed "Pos" uses it.
  var POS_ORDER = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DEF: 5 };
  function posValue(td) {
    var t = (td.textContent || '').trim().toUpperCase();
    return Object.prototype.hasOwnProperty.call(POS_ORDER, t) ? POS_ORDER[t] : 99;
  }
  function makeSortable(table) {
    if (table.dataset.sortable || table.closest('.nosort')) return;
    table.dataset.sortable = '1';
    // The clickable header row is the LAST row of <thead> -- a table with a
    // spanning group-label row above its real column headers (the ADP board)
    // keeps those on the second row; a plain table has just the one.
    var hrows = table.tHead && table.tHead.rows;
    var head = hrows && hrows[hrows.length - 1];
    var body = table.tBodies[0];
    if (!head || !body || body.rows.length < 2) return;
    Array.prototype.forEach.call(head.cells, function (th, i) {
      th.tabIndex = 0;
      th.setAttribute('role', 'button');
      var isPos = th.textContent.trim().toLowerCase() === 'pos';
      var run = function () {
        // Group each row with EVERY immediately-following .detail-row sibling
        // (a per-row drilldown -- possibly several rows deep) so a re-sort
        // moves the whole group, keyed on its leading data row.
        var all = Array.prototype.slice.call(body.rows);
        var groups = [];
        for (var idx = 0; idx < all.length; idx++) {
          var r = all[idx];
          if (r.classList.contains('detail-row')) continue;
          var grp = [r];
          while (all[idx + 1] && all[idx + 1].classList.contains('detail-row')) {
            grp.push(all[idx + 1]); idx++;
          }
          groups.push(grp);
        }
        // Non-data rows (a "⋯" gap) stay put.
        if (groups.some(function (g) { return g[0].cells.length <= 1; })) return;
        var asc = th.dataset.dir !== 'asc';
        Array.prototype.forEach.call(head.cells, function (o) {
          delete o.dataset.dir; o.classList.remove('sort-asc', 'sort-desc');
        });
        th.dataset.dir = asc ? 'asc' : 'desc';
        th.classList.add(asc ? 'sort-asc' : 'sort-desc');
        var overridden = groups.some(function (g) {
          return g[0].cells[i] && g[0].cells[i].dataset.sort !== undefined;
        });
        var numeric = !isPos && !overridden && groups.every(function (g) {
          return !g[0].cells[i] || sortValue(g[0].cells[i]) !== null;
        });
        groups.sort(function (a, b) {
          var x = a[0].cells[i], y = b[0].cells[i];
          if (!x || !y) return 0;
          var d = isPos ? posValue(x) - posValue(y)
            : numeric ? sortValue(x) - sortValue(y)
            : textValue(x).localeCompare(textValue(y));
          return asc ? d : -d;
        });
        groups.forEach(function (g) { g.forEach(function (r) { body.appendChild(r); }); });
      };
      th.addEventListener('click', run);
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); run(); }
      });
    });
  }
  function prepTables(root) {
    (root && root.querySelectorAll ? root : document)
      .querySelectorAll('#panel table').forEach(makeSortable);
  }
  global.SMTableSort = { makeSortable: makeSortable, prepTables: prepTables };

  // .stat-cell/.stat-flyout hover breakdown (style.css, team_profile.html's
  // per-game reconciled stat tables, same macro used by player_profile.html)
  // is CSS-only by default: a .stat-flyout anchors bottom-center via
  // position:absolute on its .stat-cell. That works until the cell sits
  // near the edge of a horizontally-scrollable ancestor (.tablewrap/
  // .dt-detail, both overflow-x:auto, which per spec also clips
  // overflow-y): the flyout renders but gets visibly cut off. Lives here,
  // not in one page's own <script>, because THREE #panel-having and
  // #panel-less pages all render this same macro output: index.html's
  // dashboard tabs (#panel, htmx-swapped), and team_profile.html /
  // player_profile.html (both standalone, #panel-less pages with their own
  // lazily-swapped sections) -- same reasoning that already put table
  // sorting here instead of duplicating it three times.
  //
  // bind(root) delegates two listener pairs on `root` (mouseenter/
  // mouseleave with capture, since neither bubbles, and focusin/focusout,
  // which do) scoped to `.stat-cell`. It never controls whether a flyout
  // shows -- CSS (:hover/:focus-within) still owns that entirely. On
  // enter/focus it measures the flyout at its normal (still-absolute)
  // position; only when an edge would be clipped by the nearest
  // overflow:auto/scroll ancestor OR the viewport does it switch the
  // flyout to .stat-flyout-declipped (position:fixed, style.css) with
  // inline top/left computed from the cell's own getBoundingClientRect(),
  // clamped into the viewport, flipping below the cell when there isn't
  // room above. Reverted on leave/blur so a plain, unclipped hover
  // elsewhere keeps the simpler default. Idempotent per root (a WeakSet,
  // not root.dataset -- `document` itself has no .dataset, and index.html
  // calls bind(document)) so a repeat call -- index.html's
  // htmx:afterSwap, or a standalone page re-invoking after its own lazy
  // section swap -- never double-binds the same root.
  var _boundRoots = typeof WeakSet === 'function' ? new WeakSet() : null;
  function bindStatFlyouts(root) {
    root = root || document;
    if (_boundRoots) {
      if (_boundRoots.has(root)) return;
      _boundRoots.add(root);
    } else if (root.dataset) {
      if (root.dataset.flyoutBound) return;
      root.dataset.flyoutBound = '1';
    }
    var GAP = 6, MARGIN = 8;
    function scroller(el) {
      var node = el.parentElement;
      while (node && node !== root) {
        var of = getComputedStyle(node).overflowX;
        if (of === 'auto' || of === 'scroll') return node;
        node = node.parentElement;
      }
      return null;
    }
    function place(cell) {
      var fly = cell.querySelector(':scope > .stat-flyout');
      if (!fly) return;
      fly.classList.remove('stat-flyout-declipped');
      fly.style.top = ''; fly.style.left = '';
      var cellBox = cell.getBoundingClientRect();
      var flyBox = fly.getBoundingClientRect();
      var vw = document.documentElement.clientWidth;
      var vh = document.documentElement.clientHeight;
      var bounds = { top: 0, left: 0, right: vw, bottom: vh };
      var scr = scroller(cell);
      if (scr) {
        var scrBox = scr.getBoundingClientRect();
        bounds.top = Math.max(bounds.top, scrBox.top);
        bounds.left = Math.max(bounds.left, scrBox.left);
        bounds.right = Math.min(bounds.right, scrBox.right);
        bounds.bottom = Math.min(bounds.bottom, scrBox.bottom);
      }
      var clipped = flyBox.top < bounds.top || flyBox.bottom > bounds.bottom ||
        flyBox.left < bounds.left || flyBox.right > bounds.right;
      if (!clipped) return;
      var width = flyBox.width;
      var top = cellBox.top - GAP - flyBox.height;
      if (top < MARGIN) top = cellBox.bottom + GAP;
      top = Math.max(MARGIN, Math.min(top, vh - flyBox.height - MARGIN));
      var left = cellBox.left + cellBox.width / 2 - width / 2;
      left = Math.max(MARGIN, Math.min(left, vw - width - MARGIN));
      fly.classList.add('stat-flyout-declipped');
      fly.style.top = top + 'px';
      fly.style.left = left + 'px';
    }
    function clear(cell) {
      var fly = cell.querySelector(':scope > .stat-flyout');
      if (!fly) return;
      fly.classList.remove('stat-flyout-declipped');
      fly.style.top = ''; fly.style.left = '';
    }
    root.addEventListener('mouseenter', function (e) {
      var cell = e.target.closest && e.target.closest('.stat-cell');
      if (cell) place(cell);
    }, true);
    root.addEventListener('focusin', function (e) {
      var cell = e.target.closest && e.target.closest('.stat-cell');
      if (cell) place(cell);
    });
    root.addEventListener('mouseleave', function (e) {
      var cell = e.target.closest && e.target.closest('.stat-cell');
      if (cell) clear(cell);
    }, true);
    root.addEventListener('focusout', function (e) {
      var cell = e.target.closest && e.target.closest('.stat-cell');
      if (cell) clear(cell);
    });
  }
  global.SMStatFlyouts = { bind: bindStatFlyouts };
})(window);
