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
    var head = table.tHead && table.tHead.rows[0];
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
})(window);
