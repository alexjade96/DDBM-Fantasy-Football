/* Visual playoff-bracket builder (the default editor on the Playoffs tab).
 *
 * Edits a bracket CONFIG directly, but never shows JSON: teams are dropdowns
 * (seeds + "Winner of <matchup>"), lineups are dropdowns of the team's real
 * players for that week (pre-filled from Sleeper), and the bracket preview
 * updates live. It sits on top of window.SMBracket (persistence + scoring) and
 * the /playoffs data endpoints; the raw JSON is tucked behind "Advanced".
 */
(function () {
  function enc(x) { return encodeURIComponent(x == null ? '' : x); }
  function elt(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function opt(value, label, selected) {
    var o = elt('option'); o.value = value; o.textContent = label; o.selected = !!selected; return o;
  }
  async function getJSON(url) {
    var r = await fetch(url); var j = await r.json();
    if (!r.ok || (j && j.error)) throw new Error((j && j.error) || ('HTTP ' + r.status));
    return j;
  }

  window.SMBuilder = {
    cfg: null,
    seeds: [],
    _seedsFor: null,
    _timer: null,

    _el: function (id) { return document.getElementById(id); },
    _league: function () { return SMBracket._league(); },
    _season: function () { return SMBracket._season(); },
    _theme: function () { var t = this._el('theme'); return t ? t.value : 'light'; },
    msg: function (html, cls) { SMBracket.msg(html, cls); },

    // Open/refresh the builder: seeds + a starting config (saved > committed >
    // scaffold), then render and preview. Seeds are fetched in PARALLEL with the
    // config and the structure is rendered as soon as the config lands -- the
    // first season assemble is slow (cold cache), so blocking the whole editor on
    // it made the panel look stuck/blank. Once seeds arrive the dropdowns
    // re-render with their options (kept team values survive the gap).
    init: async function () {
      if (!this._el('bkr-visual')) return;
      this.msg('Loading bracket…', '');
      var seedP = this._ensureSeeds(this._season());   // in flight; awaited below
      var cfg = SMBracket.saved();
      if (!cfg) cfg = await this._tryCfg('/playoffs/default?league=' + enc(this._league()) + '&season=' + enc(this._season()) + '&source=committed');
      if (!cfg) cfg = await this._tryCfg('/playoffs/scaffold?league=' + enc(this._league()) + '&season=' + enc(this._season())
        + '&weeks=' + enc(this._el('bkr-weeks').value) + '&teams=' + enc(this._el('bkr-teams').value));
      if (!cfg) cfg = { season: this._season(), league_id: this._league(), rounds: [] };
      this.setCfg(cfg);       // structure visible now, even if seeds are still loading
      this.preview();
      await seedP;            // populate the dropdowns once seeds land
      if (this.cfg) this.render();
      this.msg('', '');
    },
    _tryCfg: async function (url) { try { return await getJSON(url); } catch (e) { return null; } },
    // Fetch + cache the seed pool for a season. Cached across init calls (so
    // re-opening the editor is instant) and self-healing: a failed/empty fetch
    // leaves seeds empty and is retried on the next call rather than sticking.
    _ensureSeeds: async function (season) {
      if (this._seedsFor === season && this.seeds.length) return;
      try {
        this.seeds = await getJSON('/playoffs/seeds?league=' + enc(this._league()) + '&season=' + enc(season));
        if (this.seeds.length) this._seedsFor = season;
      } catch (e) { this.seeds = []; }
    },

    setCfg: function (cfg) {
      this.cfg = cfg;
      this.render();
      var t = this._el('bkr-json'); if (t) t.value = JSON.stringify(cfg, null, 2);
    },

    // ---- rendering -------------------------------------------------------
    render: function () {
      var host = this._el('bkr-visual'); if (!host) return;
      // Self-heal: if the team dropdowns would be empty (seeds never arrived),
      // fetch them and redraw. Covers a structural edit made while the first
      // season assemble was still in flight.
      if (!this.seeds.length) {
        var self0 = this;
        this._ensureSeeds(this._season()).then(function () {
          if (self0.seeds.length) self0.render();
        });
      }
      host.innerHTML = '';
      var self = this, rounds = (this.cfg && this.cfg.rounds) || [];
      rounds.forEach(function (rd, ri) {
        var col = elt('div', 'bkr-round');
        col.appendChild(self._roundHead(rd, ri));
        (rd.matchups || []).forEach(function (mu) { col.appendChild(self._card(mu, ri, rd)); });
        // Add-a-matchup row: a Game (home vs away) or a Bye (a team that
        // advances without playing) -- this is how a seeded-bye ladder like 2025
        // is built without touching JSON.
        var add = elt('div', 'bkr-addrow');
        var g = elt('button', 'ghost bkr-mini', '+ Game'); g.type = 'button';
        g.onclick = function () { self._addMatchup(ri, 'game'); };
        var b = elt('button', 'ghost bkr-mini', '+ Bye'); b.type = 'button';
        b.onclick = function () { self._addMatchup(ri, 'bye'); };
        add.appendChild(g); add.appendChild(b);
        col.appendChild(add);
        host.appendChild(col);
      });
      var addcol = elt('div', 'bkr-round bkr-addround');
      var ar = elt('button', 'ghost bkr-mini', '+ Round'); ar.type = 'button';
      ar.onclick = function () { self._addRound(); };
      addcol.appendChild(ar);
      host.appendChild(addcol);
    },

    _roundHead: function (rd, ri) {
      var self = this, head = elt('div', 'bkr-rhead');
      head.appendChild(elt('span', 'bkr-rname', (rd.name || rd.id || ('Round ' + (ri + 1)))));
      var wk = elt('input', 'bkr-wk'); wk.value = (rd.weeks || []).join(',');
      wk.title = 'Week(s), comma-separated'; wk.setAttribute('aria-label', 'Weeks');
      wk.onchange = function () {
        rd.weeks = wk.value.split(',').map(function (x) { return parseInt(x, 10); })
          .filter(function (n) { return !isNaN(n); });
        self._sync(); self.preview();
      };
      head.appendChild(wk);
      var rm = elt('button', 'bkr-x', '✕'); rm.type = 'button'; rm.title = 'Remove round';
      rm.onclick = function () { self._removeRound(ri); };
      head.appendChild(rm);
      return head;
    },

    // The concrete teams available in a round: the teams that appeared in the
    // PREVIOUS round (bye teams + game participants), so each round narrows to
    // who could actually be in it. Round 1 is the seed pool.
    _roundTeams: function (ri) {
      if (ri <= 0) return this.seeds.map(function (s) { return String(s.name); });
      var prev = this.cfg.rounds[ri - 1] || {}, out = [], seen = {};
      (prev.matchups || []).forEach(function (m) {
        ['bye', 'home', 'away'].forEach(function (k) {
          var t = k === 'bye' ? m.bye : (m[k] && m[k].team);
          if (t && String(t).indexOf('W:') !== 0 && !seen[t]) { seen[t] = 1; out.push(String(t)); }
        });
      });
      return out;
    },
    // Reference options for the previous round's advancers -- a game's winner or
    // a bye. Labelled from structure (not id), so a bye reads "Round X Bye Y".
    _prevAdvancers: function (ri) {
      if (ri <= 0) return [];
      var prev = this.cfg.rounds[ri - 1] || {}, rnum = ri, g = 0, b = 0, out = [];
      (prev.matchups || []).forEach(function (m) {
        if (Object.prototype.hasOwnProperty.call(m, 'bye')) { b++; out.push({ value: 'W:' + m.id, label: 'Round ' + rnum + ' Bye ' + b }); }
        else { g++; out.push({ value: 'W:' + m.id, label: 'Winner of Round ' + rnum + ' Game ' + g }); }
      });
      return out;
    },
    _teamOptions: function (ri, withRefs) {
      var seedOf = {};
      this.seeds.forEach(function (s) { seedOf[String(s.name)] = s.seed; });
      var out = this._roundTeams(ri).map(function (t) { return { value: t, label: (seedOf[t] ? '#' + seedOf[t] + ' ' : '') + t }; });
      return withRefs ? out.concat(this._prevAdvancers(ri)) : out;
    },
    // A bye is a specific team sitting a round out, so it can be ANY seed --
    // never scoped to the prior round, so it's insertable before earlier rounds
    // are filled (that chicken-and-egg is what made a bye slot look unfillable).
    _seedOptions: function () {
      return this.seeds.map(function (s) { return { value: String(s.name), label: '#' + s.seed + ' ' + s.name }; });
    },
    // Human label for a raw W: reference (for a preserved value not in the pool).
    _refLabel: function (value) {
      var v = String(value); if (v.indexOf('W:') !== 0) return v;
      var m = v.slice(2).match(/^R(\d+)([MB])(\d+)$/);
      if (!m) return 'Winner of ' + v.slice(2);
      return m[2] === 'B' ? ('Round ' + m[1] + ' Bye ' + m[3]) : ('Winner of Round ' + m[1] + ' Game ' + m[3]);
    },
    _pickSelect: function (cur, blank, options, onchange) {
      var self = this, sel = elt('select', 'bkr-team'), found = false;
      sel.appendChild(opt('', blank, cur === ''));
      options.forEach(function (o) { var s = cur === o.value; if (s) found = true; sel.appendChild(opt(o.value, o.label, s)); });
      if (cur && !found) sel.appendChild(opt(cur, self._refLabel(cur), true));   // keep a loaded value
      sel.onchange = function () { onchange(sel.value); };
      return sel;
    },

    _teamSelect: function (mu, ri, key) {
      var self = this;
      var cur = mu[key] && mu[key].team != null ? String(mu[key].team) : '';
      // Re-render on change: a pick changes what the NEXT round has available.
      return this._pickSelect(cur, '— team —', this._teamOptions(ri, true), function (v) {
        if (!mu[key]) mu[key] = { team: '', starters: [] };
        mu[key].team = v; mu[key].starters = [];   // lineup belonged to the old team
        self.setCfg(self.cfg); self.preview();
      });
    },

    _chead: function (mu, ri) {
      var self = this, head = elt('div', 'bkr-chead');
      head.appendChild(elt('span', 'bkr-mid', mu.id || ''));
      if (!Object.prototype.hasOwnProperty.call(mu, 'bye')) {
        var fin = elt('label', 'bkr-fin');
        var cb = elt('input'); cb.type = 'checkbox'; cb.checked = (this.cfg.final === mu.id);
        cb.onchange = function () {
          if (cb.checked) self.cfg.final = mu.id;
          else if (self.cfg.final === mu.id) delete self.cfg.final;
          self.setCfg(self.cfg); self.preview();
        };
        fin.appendChild(cb); fin.appendChild(document.createTextNode('final'));
        head.appendChild(fin);
      }
      var x = elt('button', 'bkr-x', '✕'); x.type = 'button'; x.title = 'Remove matchup';
      x.onclick = function () { self._removeMatchup(ri, mu.id); };
      head.appendChild(x);
      return head;
    },

    _card: function (mu, ri, rd) {
      var self = this, card = elt('div', 'bkr-card');
      card.appendChild(this._chead(mu, ri));
      if (Object.prototype.hasOwnProperty.call(mu, 'bye')) {
        var row = elt('div', 'bkr-side');
        // A bye team can be any seed (see _seedOptions), so it's always fillable.
        row.appendChild(this._pickSelect(mu.bye == null ? '' : String(mu.bye), '— bye team —',
          this._seedOptions(), function (v) { mu.bye = v; self.setCfg(self.cfg); self.preview(); }));
        row.appendChild(elt('span', 'tag', 'bye'));
        card.appendChild(row);
        return card;
      }
      ['home', 'away'].forEach(function (key) {
        var row = elt('div', 'bkr-side');
        row.appendChild(self._teamSelect(mu, ri, key));
        var btn = elt('button', 'ghost bkr-lineup-btn', 'lineup'); btn.type = 'button';
        btn.onclick = function () { self._toggleLineup(card, mu, key, rd); };
        row.appendChild(btn);
        card.appendChild(row);
      });
      card.appendChild(elt('div', 'bkr-lineups'));
      return card;
    },

    // ---- structural edits (games / byes / rounds) ------------------------
    _nextId: function (rd, ri, kind) {
      var prefix = 'R' + (ri + 1) + (kind === 'bye' ? 'B' : 'M');
      var have = (rd.matchups || []).map(function (m) { return m.id; });
      var n = 1; while (have.indexOf(prefix + n) >= 0) n++;
      return prefix + n;
    },
    _addMatchup: function (ri, kind) {
      var rd = this.cfg.rounds[ri]; rd.matchups = rd.matchups || [];
      if (kind === 'bye') rd.matchups.push({ id: this._nextId(rd, ri, 'bye'), bye: '' });
      else rd.matchups.push({ id: this._nextId(rd, ri, 'game'),
        home: { team: '', starters: [] }, away: { team: '', starters: [] } });
      this.setCfg(this.cfg); this.preview();
    },
    _removeMatchup: function (ri, mid) {
      var rd = this.cfg.rounds[ri];
      rd.matchups = (rd.matchups || []).filter(function (m) { return m.id !== mid; });
      if (this.cfg.final === mid) delete this.cfg.final;
      this.setCfg(this.cfg); this.preview();
    },
    _addRound: function () {
      this.cfg.rounds = this.cfg.rounds || [];
      var last = this.cfg.rounds[this.cfg.rounds.length - 1];
      var nextWk = last && last.weeks && last.weeks.length ? Math.max.apply(null, last.weeks) + 1 : '';
      var r = this.cfg.rounds.length + 1;
      this.cfg.rounds.push({ id: 'R' + r, name: 'Round ' + r,
        weeks: nextWk === '' ? [] : [nextWk], matchups: [] });
      this.setCfg(this.cfg); this.preview();
    },
    _removeRound: function (ri) {
      this.cfg.rounds.splice(ri, 1);
      this.setCfg(this.cfg); this.preview();
    },

    _closeLineups: function (node) {
      var card = node.closest('.bkr-card'); if (!card) return;
      var box = card.querySelector('.bkr-lineups'); if (box) { box.innerHTML = ''; box._openKey = null; }
    },

    _toggleLineup: async function (card, mu, key, rd) {
      var box = card.querySelector('.bkr-lineups');
      if (box._openKey === key) { box.innerHTML = ''; box._openKey = null; return; }
      box._openKey = key;
      var name = mu[key] && mu[key].team;
      if (!name || String(name).indexOf('W:') === 0) {
        box.innerHTML = ''; box.appendChild(elt('p', 'q', 'Pick a team first — the lineup opens once it is a concrete manager.'));
        return;
      }
      box.innerHTML = ''; box.appendChild(elt('p', 'q', 'Loading lineup…'));
      var wk = (rd.weeks && rd.weeks[0]) || '';
      try {
        var data = await getJSON('/playoffs/roster?league=' + enc(this._league()) + '&season=' + enc(this._season())
          + '&team=' + enc(name) + '&week=' + enc(wk));
        this._renderLineup(box, mu, key, data);
      } catch (e) {
        box.innerHTML = ''; box.appendChild(elt('p', 'bkr-msg err', 'Could not load the roster for ' + name + '.'));
      }
    },

    // Greedy map of a flat starters list onto ordered slots (mirrors the
    // server's assign_slots) so an existing lineup pre-selects the right slots.
    _assign: function (starters, slots, players) {
      var byId = {}; players.forEach(function (p) { byId[String(p.id)] = p; });
      var used = {}, picks = [];
      slots.forEach(function (slot) {
        var pick = '';
        for (var j = 0; j < starters.length; j++) {
          var pid = String(starters[j]); if (used[pid]) continue;
          var pos = (byId[pid] || {}).position;
          if (slot.eligible.indexOf(pos) >= 0) { pick = pid; used[pid] = 1; break; }
        }
        picks.push(pick);
      });
      return picks;
    },

    _renderLineup: function (box, mu, key, data) {
      var self = this, slots = data.slots || [], players = data.players || [];
      var starters = (mu[key].starters && mu[key].starters.length) ? mu[key].starters : (data.prefill || []);
      var perSlot = this._assign(starters, slots, players);
      box.innerHTML = '';
      box.appendChild(elt('div', 'bkr-ltitle', mu[key].team + ' — week ' + (data.week || '')));
      var selects = [];
      slots.forEach(function (slot, i) {
        var row = elt('div', 'bkr-slot');
        row.appendChild(elt('span', 'bkr-slab', slot.slot));
        var sel = elt('select');
        sel.appendChild(opt('', '— empty —', !perSlot[i]));
        players.forEach(function (p) { sel.appendChild(opt(p.id, p.name + ' · ' + p.position, String(perSlot[i]) === String(p.id))); });
        sel.onchange = function () {
          mu[key].starters = selects.map(function (s) { return s.value; }).filter(Boolean);
          self._sync(); self.preview();
        };
        selects.push(sel);
        row.appendChild(sel); box.appendChild(row);
      });
      // Persist the prefill so it survives even if the user opens then closes.
      if (!(mu[key].starters && mu[key].starters.length)) {
        mu[key].starters = perSlot.filter(Boolean);
        this._sync();
      }
    },

    // ---- preview / apply / io -------------------------------------------
    _sync: function () { var t = this._el('bkr-json'); if (t) t.value = JSON.stringify(this.cfg, null, 2); },

    preview: function () {
      var self = this;
      clearTimeout(this._timer);
      this._timer = setTimeout(function () { self._doPreview(); }, 350);
    },
    _doPreview: async function () {
      var j = await SMBracket.score(this.cfg);
      var img = this._el('bkr-preview');
      if (j.ok && img) {
        img.src = '/chart/bracket?league=' + enc(this._league()) + '&season=' + enc(this._season())
          + '&theme=' + enc(this._theme()) + '&bracket=' + enc(j.token) + '&_=' + Date.now();
        var champ = j.champion ? ('Champion: ' + j.champion) : 'In progress';
        if (j.warnings && j.warnings.length) this.msg(champ + ' · ' + j.warnings.length + ' still to fill', 'warn');
        else this.msg(champ + ' · looks complete', 'ok');
      } else {
        this.msg('Cannot preview — ' + ((j.errors || ['unknown error']).join('; ')), 'err');
      }
    },

    apply: async function () {
      var j = await SMBracket.apply(this.cfg);        // scores + reloads the tab
      if (j && !j.ok) this.msg('Not applied — ' + (j.errors || []).join('; '), 'err');
    },
    validate: async function () {
      try {
        var r = await fetch('/playoffs/validate?league=' + enc(this._league()),
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this.cfg) });
        var j = await r.json();
        if (j.errors && j.errors.length) this.msg('Errors: ' + j.errors.join('; '), 'err');
        else if (j.warnings && j.warnings.length) this.msg('Valid, still to fill: ' + j.warnings.join('; '), 'warn');
        else this.msg('Valid and complete.', 'ok');
      } catch (e) { this.msg('Validate failed: ' + e, 'err'); }
    },

    scaffold: async function () {
      var cfg = await this._tryCfg('/playoffs/scaffold?league=' + enc(this._league()) + '&season=' + enc(this._season())
        + '&weeks=' + enc(this._el('bkr-weeks').value) + '&teams=' + enc(this._el('bkr-teams').value));
      if (cfg) { this.setCfg(cfg); this.preview(); this.msg('New scaffold — edit teams and lineups.', ''); }
      else this.msg('Could not scaffold.', 'err');
    },
    loadInto: async function (source) {
      var cfg = await this._tryCfg('/playoffs/default?league=' + enc(this._league()) + '&season=' + enc(this._season()) + '&source=' + source);
      if (cfg) { this.setCfg(cfg); this.preview(); this.msg('Loaded ' + source + ' bracket.', ''); }
      else this.msg('No ' + source + ' bracket for this season.', 'err');
    },
    download: function () {
      var cfg = this.cfg; if (!cfg) return;
      var blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' });
      var a = elt('a'); a.href = URL.createObjectURL(blob);
      a.download = (cfg.season || 'playoff') + '_bracket.json';
      a.click(); URL.revokeObjectURL(a.href);
    },
    upload: function (input) {
      var f = input.files && input.files[0]; if (!f) return;
      var self = this, rd = new FileReader();
      rd.onload = function () {
        try { self.setCfg(JSON.parse(rd.result)); self.preview(); self.msg('Loaded file.', ''); }
        catch (e) { self.msg('That file is not valid JSON.', 'err'); }
      };
      rd.readAsText(f); input.value = '';
    },
    fromJson: function () {
      var t = this._el('bkr-json'); if (!t) return;
      try { this.setCfg(JSON.parse(t.value)); this.preview(); this.msg('Loaded JSON into the builder.', ''); }
      catch (e) { this.msg('That JSON is not valid: ' + e, 'err'); }
    }
  };
})();
