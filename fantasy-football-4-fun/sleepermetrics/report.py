"""Self-contained season report (mirrors R report.R).

Bundles a league's whole season -- the narrative, the headline numbers, a
per-manager breakdown, and every chart -- into ONE standalone HTML file with the
charts embedded as base64 PNGs. No external assets, so it can be emailed, dropped
in a drive, or opened offline. This is the "export" deliverable: the dashboards
are for exploring, the report is for keeping and sharing.

    from sleepermetrics import season, seasons, load_playoffs, season_report
    season_report(season(league_id), "report.html")
"""
from __future__ import annotations

import base64
import html
import io
import re
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import headshots, metrics, plots, summaries  # noqa: E402
from .season import Season, assign_slots, optimal_lineup  # noqa: E402


def _fig_uri(fig, width=1100, height=None, dpi=112) -> str:
    """Render a matplotlib figure to an inline base64 PNG data URI."""
    if height is not None:
        fig.set_size_inches(width / dpi, height / dpi)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# --- portraits, avatars, position-rank badges ---------------------------------
# The standalone file must stay self-contained (a test asserts no `src="http"`
# and it opens offline), so a portrait is fetched once via `headshots` (which
# caches to disk and honours SLEEPERMETRICS_NO_IMAGES) and then *base64-embedded*.
# The same player shows up in a dozen tables, so a portrait is NOT inlined at
# every use -- it is registered here ONCE, and `season_report()` bakes one
# `<style>` rule per unique image (`.pface[data-k="K"]{background-image:url(...)}`).
# Everything is best-effort: a miss, the disabled flag or no network gives "" and
# the caller falls back to a plain text name.

_URI_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".gif": "image/gif", ".webp": "image/webp"}
_portrait_uris: dict = {}     # cache key -> data URI ("" for a known miss)
_portrait_reg: dict = {}      # token -> data URI, for this render's <style> block
_portrait_seq = [0]


def _file_data_uri(path: str | None) -> str:
    """A local image file as a base64 data URI, or "" on any failure."""
    if not path:
        return ""
    try:
        import os
        with open(path, "rb") as fh:
            raw = fh.read()
        mime = _URI_MIME.get(os.path.splitext(path)[1].lower(), "image/png")
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    except Exception:
        return ""


def _portrait_uri(pid, position: str = "") -> str:
    """A player's Sleeper headshot (team logo for a DEF) as an embedded data URI."""
    if pid is None or headshots.disabled():
        return ""
    key = (str(pid), str(position) or "")
    if key not in _portrait_uris:
        _portrait_uris[key] = _file_data_uri(
            headshots.headshot(str(pid), position or None))
    return _portrait_uris[key]


def _avatar_uri(url) -> str:
    """A manager/team account avatar (by url) as an embedded data URI."""
    if not url or (isinstance(url, float) and url != url) or headshots.disabled():
        return ""
    u = headshots.avatar_thumb(str(url))
    if u not in _portrait_uris:
        import os
        key = "av_" + os.path.basename(u.split("?")[0])
        _portrait_uris[u] = _file_data_uri(headshots._fetch(u, key))
    return _portrait_uris[u]


def _reset_portrait_registry() -> None:
    _portrait_reg.clear()
    _portrait_seq[0] = 0


def _register_face(uri: str, cls: str) -> str:
    """Register `uri` once and return `<span class='{cls}' data-k='K'>` or ""."""
    if not uri:
        return ""
    tok = next((k for k, v in _portrait_reg.items() if v == uri), None)
    if tok is None:
        _portrait_seq[0] += 1
        tok = f"p{_portrait_seq[0]}"
        _portrait_reg[tok] = uri
    return f'<span class="{cls}" data-k="{tok}"></span>'


def _portrait_style() -> str:
    """One `<style>` block, one rule per unique portrait/avatar this render used."""
    if not _portrait_reg:
        return ""
    rules = "".join(f'.pface[data-k="{k}"],.face[data-k="{k}"]'
                    f'{{background-image:url({v})}}'
                    for k, v in _portrait_reg.items())
    return f"<style>{rules}</style>"


def _pface(pid, position: str = "") -> str:
    """A player portrait token (deduped via the registry), or "" if none."""
    return _register_face(_portrait_uri(pid, position), "pface")


def _face(url) -> str:
    """A manager/team account avatar token (deduped), or "" if none."""
    return _register_face(_avatar_uri(url), "face")


def _rank_badge(position, rank) -> str:
    """The site's `POS #rank` badge (e.g. "WR #4"), or "" if the rank is unknown."""
    if rank is None or (isinstance(rank, float) and rank != rank):
        return ""
    return (f"<span class='q posrank'>{html.escape(str(position))} "
            f"#{int(rank)}</span>")


def _rank_of(ranks: dict | None, pid) -> int | None:
    """This player's season position rank from a `season_position_ranks()` map."""
    if not ranks or pid is None:
        return None
    e = ranks.get(str(pid))
    return int(e["rank"]) if e else None


def _md(text: str) -> str:
    """The summaries' small markdown subset (###, -, **bold**) to safe HTML."""
    out, ul = [], False
    for line in html.escape(text or "").splitlines():
        import re
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line.startswith("### "):
            continue                      # the report supplies its own heading
        if line.startswith("- "):
            if not ul:
                out.append("<ul>")
                ul = True
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip():
            if ul:
                out.append("</ul>")
                ul = False
            out.append(f"<p>{line}</p>")
    if ul:
        out.append("</ul>")
    return "\n".join(out)


def _fig(fn, *args, **kw):
    """Render a chart function to a <figure> with an embedded PNG, or '' on failure."""
    try:
        d = kw.pop("_desc", "")
        uri = _fig_uri(fn(*args, **kw))
    except Exception:
        return ""
    cap = f'<figcaption>{html.escape(d)}</figcaption>' if d else ""
    return f'<figure><img src="{uri}" alt="{html.escape(d)}">{cap}</figure>'


def _has_scored_week(s: Season) -> bool:
    """True once at least one regular-season week carries a real score. Before
    that every performance figure in the report is a zero (a drafted-but-not-
    started season), so the report is skipped entirely -- the webapp mirror of
    this gate is app._has_scored_data."""
    tw = getattr(s, "team_wk", None)
    if tw is None or not len(tw) or "points" not in getattr(tw, "columns", []):
        return False
    return bool(pd.to_numeric(tw["points"], errors="coerce").fillna(0).gt(0).any())


def _insight_tiles(s: Season) -> list[dict]:
    """The season's headline numbers as MERGED good/bad insight tiles.

    Mirrors the webapp Overview tab's `_overview_insight_rows` (app.py) -- the
    same six opposed metrics (the table, coaching, luck, points allowed,
    consistency, schedule), the same `{label, rows: [{tone, holder, value,
    detail}, ...]}` shape, computed from the same `metrics.*`. Ordered most
    telling first. The champion is deliberately NOT here -- the report's own
    `<h1>` names them and the narrative leads with them.

    `_overview_insight_rows` itself lives in the webapp, not the package, so it
    can't be imported here; this is the package-local copy, kept in step with it.

    Returns [] until at least one week has been scored -- before that every
    one of these facts is a zero (a drafted-but-not-started season), so the
    report drops the tile grid entirely, same as the webapp Overview does.
    """
    if not _has_scored_week(s):
        return []

    tiles: list[dict] = []

    def _ok(holder):
        return holder is not None and not (isinstance(holder, float)
                                           and pd.isna(holder))

    def merged(label, best, worst):
        """best/worst are (holder, value, detail) triples; either may be None."""
        rows = [{"tone": tone, "holder": str(trip[0]), "value": trip[1],
                 "detail": trip[2]}
                for tone, trip in (("good", best), ("bad", worst))
                if trip is not None and _ok(trip[0])]
        if rows:
            tiles.append({"label": label, "rows": rows})

    st = getattr(s, "standings", None)
    if st is None or not len(st):
        return tiles

    lead, tail = st.iloc[0], st.iloc[-1]
    merged("The table",
           (lead["user_name"], f"{int(lead['wins'])}-{int(lead['losses'])}",
            f"top of the table, {round(lead['points'])} pts for"),
           (tail["user_name"], f"{int(tail['wins'])}-{int(tail['losses'])}",
            f"bottom of the table, {round(tail['points'])} pts for")
           if len(st) >= 2 else None)

    eff = metrics.efficiency(s)
    if len(eff) >= 2:
        best_c, worst_c = eff.iloc[0], eff.iloc[-1]
        merged("Coaching",
               (best_c["user_name"], f"{best_c['eff']:.1f}%",
                "of the optimal lineup started"),
               (worst_c["user_name"], f"{worst_c['eff']:.1f}%",
                "of the optimal lineup started"))
    elif len(eff) == 1:
        best_c = eff.iloc[0]
        merged("Coaching",
               (best_c["user_name"], f"{best_c['eff']:.1f}%",
                "of the optimal lineup started"), None)

    lk = metrics.luck(s)
    if len(lk) >= 2:
        lucky, unlucky = lk.iloc[0], lk.iloc[-1]
        merged("Luck",
               (lucky["user_name"], f"{lucky['luck']:+.1f}",
                "wins vs. all-play expectation"),
               (unlucky["user_name"], f"{unlucky['luck']:+.1f}",
                "wins vs. all-play expectation"))

    pfa = metrics.points_for_against(s)
    if len(pfa) >= 2:
        stingy = pfa.loc[pfa["pa"].idxmin()]
        leaky = pfa.loc[pfa["pa"].idxmax()]
        merged("Points allowed",
               (stingy["user_name"], f"{round(stingy['pa'])}",
                "fewest conceded all season"),
               (leaky["user_name"], f"{round(leaky['pa'])}",
                "most conceded all season"))

    cons = metrics.consistency(s)
    if len(cons) >= 2:
        steady, swingy = cons.iloc[0], cons.iloc[-1]
        # SD is undefined with a single scored week (a just-started season) --
        # skip the tile rather than formatting a NaN.
        if pd.notna(steady["sd"]) and pd.notna(swingy["sd"]):
            merged("Consistency",
                   (steady["user_name"], f"SD {round(steady['sd'])}",
                    "smallest week-to-week swing"),
                   (swingy["user_name"], f"SD {round(swingy['sd'])}",
                    "biggest week-to-week swing"))

    sos = metrics.strength_of_schedule(s)
    if len(sos) >= 2:
        hard = sos.loc[sos["sos"].idxmax()]
        easy = sos.loc[sos["sos"].idxmin()]
        merged("Schedule",
               (easy["user_name"], f"{easy['sos']:.1f}",
                "easiest, opponent pts/week faced"),
               (hard["user_name"], f"{hard['sos']:.1f}",
                "toughest, opponent pts/week faced"))
    return tiles


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _manager_tiles(s: Season, manager: str) -> list[tuple[str, str, str]]:
    """The headline numbers scoped to one manager. Only called for a manager the
    season actually has (report_parts gates on it), so the empty case is a
    defensive [] rather than a whole-league fallback of a different shape."""
    st = s.standings
    row = st[st["user_name"] == manager]
    if row.empty:
        return []
    r = row.iloc[0]
    n = len(st)
    pf_rank = int((st["points"] > r["points"]).sum()) + 1
    apr = metrics.allplay(s).query("user_name == @manager").iloc[0]
    lkr = metrics.luck(s).query("user_name == @manager").iloc[0]
    er = metrics.efficiency(s).query("user_name == @manager").iloc[0]
    tw = s.team_wk[s.team_wk["user_name"] == manager]
    best = tw.loc[tw["points"].idxmax()]
    return [
        ("Finish", "Champion" if bool(r["champion"]) else f"#{int(r['final_position'])}",
         f"of {n} teams"),
        ("Record", f"{int(r['wins'])}-{int(r['losses'])}", "regular season"),
        ("Points for", f"{r['points']:.0f}", f"#{pf_rank} in the league"),
        ("All-play", f"{apr['allplay_pct'] * 100:.0f}%",
         f"#{int(apr['allplay_rank'])} on merit"),
        ("Luck", f"{lkr['luck']:+.1f}", "wins vs merit"),
        ("Sharpest week", f"{best['points']:.1f}",
         f"wk {int(best['week'])} · {er['eff']:.0f}% of optimal"),
    ]


def _manager_narrative(s: Season, manager: str, seasons: dict | None = None) -> str:
    """A short, manager-focused paragraph built from the season metrics."""
    st = s.standings
    row = st[st["user_name"] == manager]
    if row.empty:
        return _md(summaries.summary_season(s))
    r = row.iloc[0]
    n = len(st)
    apr = metrics.allplay(s).query("user_name == @manager").iloc[0]
    lkr = metrics.luck(s).query("user_name == @manager").iloc[0]
    er = metrics.efficiency(s).query("user_name == @manager").iloc[0]
    tw = s.team_wk[s.team_wk["user_name"] == manager]
    best, worst = tw.loc[tw["points"].idxmax()], tw.loc[tw["points"].idxmin()]
    lk = lkr["luck"]
    luck_txt = ("the schedule flattered them" if lk > 0.5 else
                "the schedule robbed them" if lk < -0.5 else "the schedule was fair")
    who = html.escape(str(manager))
    ps = [
        f"<strong>{who}</strong> finished {_ordinal(int(r['final_position']))} of {n} "
        f"at {int(r['wins'])}-{int(r['losses'])}, scoring {r['points']:.0f} points. "
        f"On all-play (every team, every week) they ranked #{int(apr['allplay_rank'])}, "
        f"so {luck_txt} ({lk:+.1f} wins vs merit).",
        f"Their ceiling was {best['points']:.1f} in week {int(best['week'])} and their "
        f"floor {worst['points']:.1f} in week {int(worst['week'])}; they set the optimal "
        f"lineup {er['eff']:.0f}% of the time.",
    ]
    if seasons and len(seasons) > 1:
        hh = metrics.head_to_head(seasons)
        hh = hh[hh["user_name"] == manager]
        hh = hh[hh["games"] >= 2]
        if len(hh):
            own = hh.loc[hh["win_pct"].idxmax()]
            nem = hh.loc[hh["win_pct"].idxmin()]
            if own["opp_name"] != nem["opp_name"]:
                ps.append(
                    f"All-time they own <strong>{html.escape(str(own['opp_name']))}</strong> "
                    f"({int(own['wins'])}-{int(own['losses'])}) but can't solve "
                    f"<strong>{html.escape(str(nem['opp_name']))}</strong> "
                    f"({int(nem['wins'])}-{int(nem['losses'])}).")
    return "".join(f"<p>{p}</p>" for p in ps)


def _team_table(s: Season, highlight: str | None = None) -> str:
    """One row per manager: the season on a line. `highlight` marks one row."""
    st = s.standings[["user_name", "wins", "losses", "points", "pa", "final_position"]]
    ap = metrics.allplay(s)[["user_name", "allplay_pct", "rank_delta"]]
    pw = metrics.power_rank(s)[["user_name", "power_rank"]]
    mp = metrics.manager_profile(s)[["user_name", "moves", "trades", "lineup_iq"]]
    d = (st.merge(ap, on="user_name").merge(pw, on="user_name").merge(mp, on="user_name")
         .sort_values("final_position"))
    rows = []
    for _, r in d.iterrows():
        gap = "even" if r["rank_delta"] == 0 else f"{r['rank_delta']:+d}"
        me = " class='me'" if highlight and r["user_name"] == highlight else ""
        rows.append(
            f"<tr{me}><td class='rank'>{int(r['final_position'])}</td>"
            f"<td class='name'>{html.escape(str(r['user_name']))}</td>"
            f"<td>{int(r['wins'])}-{int(r['losses'])}</td>"
            f"<td class='n'>{r['points']:.0f}</td>"
            f"<td class='n'>{r['pa']:.0f}</td>"
            f"<td class='n'>{r['allplay_pct'] * 100:.0f}%</td>"
            f"<td class='n'>#{int(r['power_rank'])}</td>"
            f"<td class='n'>{r['lineup_iq']:.0f}%</td>"
            f"<td class='n'>{int(r['moves'])}/{int(r['trades'])}</td></tr>")
    return (
        "<table class='teams lead'><thead><tr>"
        "<th>#</th><th>Manager</th><th>Record</th><th class='n'>PF</th>"
        "<th class='n'>PA</th><th class='n'>All-play</th><th class='n'>Power</th>"
        "<th class='n'>Lineup IQ</th><th class='n'>Moves/Trades</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _section(title, blurb, *figs) -> str:
    """A grid of figures. An empty title continues the section above it --
    that's how a section carrying both a table and charts avoids a repeated
    heading."""
    body = "".join(f for f in figs if f)
    if not body:
        return ""
    head = f"<h2>{html.escape(title)}</h2>" if title else ""
    sub = f"<p class='blurb'>{html.escape(blurb)}</p>" if blurb else ""
    return f"<section>{head}{sub}<div class='grid'>{body}</div></section>"


def _html_section(title: str, blurb: str, inner: str) -> str:
    """A section whose body is a raw HTML table (not a grid of figures).

    An empty `title` makes this a CONTINUATION of the section above it (no
    `<h2>`) -- its own independent `<section>`/`.teamsec` block, just under
    the same heading. `.contd` gets the inter-block spacing the missing
    heading would otherwise have supplied."""
    if not inner:
        return ""
    sub = f"<p class='blurb'>{html.escape(blurb)}</p>" if blurb else ""
    if not title:
        return (f"<section class='contd'>{sub}"
                f"<div class='teamsec'>{inner}</div></section>")
    return (f"<section><h2>{html.escape(title)}</h2>{sub}"
            f"<div class='teamsec'>{inner}</div></section>")


def _split_section(title: str, blurb: str, parts: tuple, table_blurb: str) -> list:
    """Turn a `(facts_html, table_html)` pair into up to two section tuples --
    the facts under `title`/`blurb`, then the table as an independent
    continuation block (empty title, its own `table_blurb`) so the two read
    as separate objects under one heading rather than one glued-together
    body. Degrades to a single normally-titled section when only one part
    is present."""
    facts_html, table_html = parts
    if facts_html and table_html:
        return [(title, blurb, facts_html, []),
                ("", table_blurb, table_html, [])]
    only = facts_html or table_html
    return [(title, blurb, only, [])] if only else []


def _neighborhood(s: Season, manager: str) -> str:
    """The standings slice around one manager: the leader, their neighbours, last."""
    st = s.standings.sort_values("final_position").reset_index(drop=True)
    if manager not in set(st["user_name"]):
        return ""
    i = int(st.index[st["user_name"] == manager][0])
    n = len(st)
    idxs = sorted({0, i - 1, i, i + 1, n - 1} & set(range(n)))
    rows, prev = [], None
    for j in idxs:
        if prev is not None and j != prev + 1:
            rows.append("<tr class='gap'><td colspan='5'>⋯</td></tr>")
        r = st.iloc[j]
        me = " class='me'" if j == i else ""
        rows.append(
            f"<tr{me}><td class='rank'>{int(r['final_position'])}</td>"
            f"<td class='name'>{html.escape(str(r['user_name']))}</td>"
            f"<td>{int(r['wins'])}-{int(r['losses'])}</td>"
            f"<td class='n'>{r['points']:.0f}</td>"
            f"<td class='n'>{r['pa']:.0f}</td></tr>")
        prev = j
    return (
        "<table class='teams lead'><thead><tr><th>#</th><th>Manager</th><th>Record</th>"
        "<th class='n'>PF</th><th class='n'>PA</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>")


def _rank_pill(rank: int, n: int) -> str:
    """A rank as a coloured badge -- top third good, bottom third bad."""
    band = max(1, round(n / 3))
    cls = "good" if rank <= band else "bad" if rank > n - band else "mid"
    return (f"<span class='rankpill {cls}'>#{rank}"
            f"<span class='of'> of {n}</span></span>")


def _rank_table(s: Season, manager: str) -> str:
    """Per-category standing: the manager's value + rank, and the best/worst team."""
    st = s.standings.set_index("user_name")
    ap = metrics.allplay(s).set_index("user_name")
    eff = metrics.efficiency(s).set_index("user_name")
    lk = metrics.luck(s).set_index("user_name")
    pw = metrics.power_rank(s).set_index("user_name")
    con = metrics.consistency(s).set_index("user_name")
    # (label, series, higher_is_better, format)
    cats = [
        ("Points for", st["points"], True, "{:.0f}"),
        ("Points against", st["pa"], False, "{:.0f}"),
        ("All-play win %", ap["allplay_pct"] * 100, True, "{:.0f}%"),
        ("Lineup efficiency", eff["eff"], True, "{:.0f}%"),
        ("Power rating", pw["power"], True, "{:+.2f}"),
        ("Luck", lk["luck"], True, "{:+.1f}"),
        ("Consistency (SD)", con["sd"], False, "{:.1f}"),
    ]
    rows = []
    for label, ser, hib, fmt in cats:
        ser = ser.dropna()
        if manager not in ser.index:
            continue
        order = ser.sort_values(ascending=not hib)   # best first
        names = list(order.index)
        rank = names.index(manager) + 1

        def _peer(nm, val):
            """The best/worst holder -- flagged when it's this manager."""
            me = " is-me" if nm == manager else ""
            return (f"<span class='peer{me}'>{html.escape(str(nm))}</span> "
                    f"<span class='q'>{fmt.format(val)}</span>")

        rows.append(
            f"<tr><td class='name'>{label}</td>"
            f"<td class='n val'>{fmt.format(ser[manager])}</td>"
            f"<td class='n'>{_rank_pill(rank, len(names))}</td>"
            f"<td>{_peer(names[0], order.iloc[0])}</td>"
            f"<td>{_peer(names[-1], order.iloc[-1])}</td></tr>")
    if not rows:
        return ""
    return (
        "<table class='teams'><thead><tr><th>Category</th><th class='n'>Them</th>"
        "<th class='n'>Rank</th><th>League best</th><th>League worst</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _mgr_postseason(s: Season, manager: str, playoffs: dict | None,
                    ranks: dict | None = None) -> str:
    """One manager's own playoff run: their games, scores, and how it ended."""
    if not playoffs or s.season not in playoffs:
        return ""
    p = playoffs[s.season]
    res = getattr(p, "results", None)
    if res is None or "team" not in res.columns:
        return ""
    mine = res[res["team"] == manager].sort_values("weeks")
    if mine.empty:
        return "<p class='blurb'>Did not reach the postseason.</p>"
    champ = getattr(p, "champion", None)
    if champ == manager:
        outcome = "Won the championship."
    else:
        nb = mine[mine["result"] != "BYE"]
        last = nb.iloc[-1] if len(nb) else None
        outcome = (f"Eliminated in {last['round']}." if last is not None
                   and last["result"] == "L" else "Reached the postseason.")
    rows = []
    for _, g in mine.iterrows():
        rnd = html.escape(str(g["round"]))
        if g["result"] == "BYE":
            # The round is already named in the Round column, so just "Bye" --
            # a team with two bye rounds otherwise read "First-round bye" twice.
            rows.append((
                [(rnd, False), ("<span class='q'>Bye</span>", False),
                 ("N/A", True), ("N/A", True), ("<span class='res'>N/A</span>", True)],
                ""))
            continue
        cls = {"W": "w", "L": "l"}.get(str(g["result"]), "")
        cells = [
            (rnd, False), (html.escape(str(g["opponent"])), False),
            (f"{g['points']:.1f}", True), (f"{g['opp_points']:.1f}", True),
            (f"<span class='res {cls}'>{g['result']}</span>", True)]
        rows.append((cells, _playoff_round_detail(s, manager, p, g, ranks)))
    table = _drill_table(
        [("Round", False), ("Opponent", False), ("PF", True), ("PA", True),
         ("Result", True)],
        "minmax(150px,1.8fr) minmax(120px,1.4fr) minmax(70px,0.8fr) "
        "minmax(70px,0.8fr) minmax(70px,0.8fr)", rows)
    return (f"<p class='blurb'>{html.escape(outcome)}</p>" + table
            + _mgr_playoff_roster(s, manager, p, ranks))


def _playoff_round_detail(s: Season, manager: str, p, g,
                          ranks: dict | None = None) -> str:
    """One playoff round expanded: both lineups side by side, plus the facts.

    The lineups come from the engine's own scored starters (`p.players`), which
    covers every round including the final -- unlike `pl_wk`, which stops at the
    scored season. Bench regret is the exception: it needs the full roster, so it
    only appears for rounds the scored season still reaches.
    """
    pp = getattr(p, "players", None)
    if pp is None or not {"team", "matchup_id", "points",
                          "player_name"}.issubset(getattr(pp, "columns", [])):
        return ""
    mu = pp[pp["matchup_id"] == g["matchup_id"]]
    mine_pl = mu[mu["team"] == manager].sort_values("points", ascending=False)
    opp_pl = mu[mu["team"] == g["opponent"]].sort_values("points", ascending=False)
    if mine_pl.empty:
        return ""
    # Points order picks out the standouts for the facts above; the lineup
    # tables below read in scoreboard order instead.
    mine_lu = assign_slots(mine_pl, s.slots)
    opp_lu = assign_slots(opp_pl, s.slots)

    facts = []
    top = mine_pl.iloc[0]
    facts.append(("Top scorer", _player_fact(top, ranks=ranks)))
    if len(mine_pl) > 1:
        facts.append(("Quietest starter", _player_fact(mine_pl.iloc[-1], ranks=ranks)))
    if not opp_pl.empty:
        facts.append((f"{g['opponent']}'s best",
                      _player_fact(opp_pl.iloc[0], ranks=ranks)))
    if pd.notna(g.get("margin")):
        m = float(g["margin"])
        shape = ("a coin flip" if abs(m) <= 10 else
                 "comfortable" if abs(m) <= 40 else "a rout")
        facts.append(("Margin", f"<span class='pts'>{m:+.1f}</span> "
                                f"<span class='q'>{shape}</span>"))
    if pd.notna(g.get("weeks")):
        facts.append(("Week(s)", html.escape(str(g["weeks"]))))
    swap = _bench_regret(s, manager, g, mine_pl, ranks)
    if swap:
        facts.append(swap)

    def lineup(df):
        return _lineup_mini(df, ranks, "slot")

    tables = ("<div class='dt-tables'>"
              + _labeled(f"{manager} · {g['points']:.1f} pts", lineup(mine_lu))
              + _labeled(f"{g['opponent']} · {g['opp_points']:.1f} pts",
                         lineup(opp_lu))
              + "</div>")
    return _facts(facts) + tables


def _mgr_playoff_roster(s: Season, manager: str, p,
                        ranks: dict | None = None) -> str:
    """Their studs and duds across the whole playoff run.

    Scored from the engine's own started-player points (`p.players`), so it
    spans every round including the final. Per-round detail -- lineups, margins,
    bench calls -- belongs to that round's drill-down, not here.
    """
    pp = getattr(p, "players", None)
    if pp is None or "team" not in getattr(pp, "columns", []):
        return ""
    mine_pl = pp[pp["team"] == manager]
    if mine_pl.empty:
        return ""
    rmap = dict(zip(p.results["round_id"], p.results["round"]))
    facts = []
    best = mine_pl.loc[mine_pl["points"].idxmax()]
    worst = mine_pl.loc[mine_pl["points"].idxmin()]
    facts.append(("Playoff MVP",
                  _player_fact(best, str(rmap.get(best["round_id"], "")),
                               ranks=ranks)))
    if len(mine_pl) > 1:
        facts.append(("Quietest starter",
                      _player_fact(worst, str(rmap.get(worst["round_id"], "")),
                                   ranks=ranks)))

    # Per-round bench regret now lives in that round's own drill-down, so this
    # block stays the run-level summary.
    return _facts(facts)


def _bench_regret(s: Season, manager: str, g, started_pl, ranks=None):
    """The bench call that cost them a playoff loss, as a (label, value) fact.

    A benched player who outscored a same-position starter. Needs the full
    roster, which `pl_wk` only carries for weeks inside the scored season -- the
    final sits past that, so it returns None there rather than guessing.
    """
    if str(g.get("result")) != "L":
        return None                      # "regret" only reads on a loss
    rid = _mgr_roster_id(s, manager)
    pl = s.pl_wk
    if rid is None or not {"roster_id", "week", "player_id", "points",
                           "position", "is_starter"}.issubset(pl.columns):
        return None
    try:
        wk = int(str(g["weeks"]).split("-")[0])
    except (ValueError, TypeError):
        return None
    if wk > s.last_week:
        return None
    started = set(started_pl["player_id"].astype(str))
    wkr = pl[(pl["roster_id"] == rid) & (pl["week"] == wk)].copy()
    wkr["player_id"] = wkr["player_id"].astype(str)
    starters = wkr[wkr["player_id"].isin(started)]
    bench = wkr[~wkr["player_id"].isin(started)]
    swap = None
    for _, b in bench.iterrows():
        same = starters[starters["position"] == b["position"]]
        if same.empty:
            continue
        weak = same.loc[same["points"].idxmin()]
        gain = float(b["points"]) - float(weak["points"])
        if gain > 0 and (swap is None or gain > swap[0]):
            swap = (gain, b, weak)
    if not swap:
        return None
    gain, b, weak = swap
    margin = abs(float(g["margin"])) if pd.notna(g.get("margin")) else None
    flip = ("would have flipped it" if margin is not None and gain >= margin
            else f"+{gain:.1f} swing")
    note = (f"benched for {html.escape(str(weak['player_name']))} "
            f"{float(weak['points']):.1f} &middot; {flip}")
    return ("Bench call", _fact_player(
        b["player_name"], b["position"], f"{float(b['points']):.1f}", note,
        pid=b.get("player_id"), ranks=ranks))


def _career_playoff_cell(year_s: Season, manager: str, p, cb: dict | None) -> str:
    """One manager's postseason result for the career table's Playoffs column.

    Split out from the regular-season rank so the two read as separate facts.
    `p` is that season's scored `Playoff` (or None if no bracket exists at all);
    `cb` is `consolation_bracket()` for teams that missed the championship
    bracket. Values: "Champion" / "Runner-up" / "Rd N" (last title-bracket
    loss) for teams in the bracket; "Won consolation" / "Lost consolation" for
    the consolation winner / first-out team; "Missed" for any other team that
    did not make the championship bracket; an en-dash when the season has no
    bracket to read at all.
    """
    if p is None:
        return "<span class='q'>&ndash;</span>"
    try:
        from .playoffs import playoff_summary
        summ = playoff_summary(p)
    except Exception:
        summ = None
    mine = summ[summ["team"] == manager] if summ is not None else None
    if mine is not None and len(mine):
        outcome = str(mine.iloc[0]["outcome"])
        if outcome == "Champion":
            return "<span class='res w'>Champion</span>"
        if outcome == "Runner-up":
            return "Runner-up"
        m = re.search(r"Round\s+(\d+)", outcome)
        if m:
            return f"<span class='res l'>Rd {m.group(1)}</span>"
        return html.escape(outcome)
    # Not in the championship bracket -- the consolation race, if there was one.
    if cb:
        if cb.get("winner") == manager:
            return "<span class='res w'>Won consolation</span>"
        if cb.get("last") == manager:
            return "<span class='res l'>Lost consolation</span>"
    return "<span class='q'>Missed</span>"


def _mgr_career(s: Season, manager: str, seasons: dict | None,
                playoffs: dict | None = None) -> str:
    """One manager's own career: a line per season, plus their all-time standing.

    The per-season line splits the old combined "Finish" (regular-season rank
    plus a champion star) into two columns: "Reg." (regular-season standing)
    and "Playoffs" (how the postseason ended -- see `_career_playoff_cell`).
    """
    if not seasons or len(seasons) < 2:
        return ""
    uid = s.standings.loc[s.standings["user_name"] == manager, "user_id"]
    if uid.empty:
        return ""
    uid = uid.iloc[0]
    playoffs = playoffs or {}
    rows = []
    for yr in sorted(seasons):
        year_s = seasons[yr]
        r = year_s.standings
        r = r[r["user_id"] == uid]
        if r.empty:
            continue
        r = r.iloc[0]
        name = str(r["user_name"])
        p = playoffs.get(str(yr))
        cb = None
        if p is not None:
            try:
                cb, _ = _consolation_of(year_s, p)
            except Exception:
                cb = None
        po = _career_playoff_cell(year_s, name, p, cb)
        rows.append(
            f"<tr><td class='rank'>{yr}</td>"
            f"<td class='n'>#{int(r['final_position'])}</td>"
            f"<td>{po}</td>"
            f"<td>{int(r['wins'])}-{int(r['losses'])}</td>"
            f"<td class='n'>{r['points']:.0f}</td></tr>")
    if not rows:
        return ""
    career = metrics.career(seasons).reset_index(drop=True)
    summary = ""
    crow = career[career["user_id"] == uid]
    if len(crow):
        c = crow.iloc[0]
        rk = list(career["user_id"]).index(uid) + 1
        summary = _facts([
            ("Career record", f"<span class='pts'>{c['record']}</span> "
                              f"<span class='q'>{c['win_pct']:.0f}%</span>"),
            ("Seasons", f"<span class='pts'>{int(c['seasons'])}</span>"),
            ("Titles", f"<span class='pts'>{int(c['titles'])}</span>"),
            ("Best finish", f"<span class='pts'>#{int(c['best'])}</span>"),
            ("All-time", _rank_pill(rk, len(career))),
        ])
    return (
        summary + "<table class='teams'><thead><tr><th>Season</th>"
        "<th class='n'>Reg.</th><th>Playoffs</th><th>Record</th>"
        "<th class='n'>PF</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _drill_table(cols: list, template: str, rows: list,
                 groups: list | None = None) -> str:
    """A table whose rows each expand to a detail panel (native <details>).

    `cols`: list of (label, is_num). `template`: CSS grid-template-columns.
    `rows`: list of (cells, detail) where `cells` is a list of (html, is_num) and
    `detail` is the HTML shown when that row is expanded ("" = not expandable).
    `groups` (optional, same convention as `_mini_table`): column-count sizes
    for conceptual clusters -- the last column of each group but the final
    one gets `.grp-end`'s wider gap (see `_CSS`'s `.drilltable .grp-end`).

    A `min-width` is set from the sum of the template's own px floors (the
    `minmax(Npx,...)` lower bounds and any bare `Npx` track) plus the grid
    gaps and row padding, so the row never shrinks below what its columns
    need -- below that `.teamsec` (which is `overflow-x:auto`) scrolls
    instead of the grid clipping a cell (the parent-row player names were
    being cut off at narrow widths).
    """
    if not rows:
        return ""
    ends = _group_ends(len(cols), groups)
    head = "".join(
        f"<span class='{'dt-num' if num else ''}{' grp-end' if i in ends else ''}'>"
        f"{html.escape(c)}</span>" for i, (c, num) in enumerate(cols))
    body = []
    for cells, detail in rows:
        sm = "".join(
            f"<span class='{'dt-num' if num else ''}{' grp-end' if i in ends else ''}'>"
            f"{c}</span>" for i, (c, num) in enumerate(cells))
        det = f"<div class='dt-detail'>{detail}</div>" if detail else ""
        body.append(f"<details class='dt-row'><summary>{sm}</summary>{det}</details>")
    floors = [int(x) for x in re.findall(r"(\d+)px", template)]
    # ~8px grid gap between tracks + ~44px of horizontal summary padding.
    min_w = sum(floors) + 8 * max(len(cols) - 1, 0) + 44
    return (f"<div class='drilltable' style='--cols:{template};"
            f"min-width:{min_w}px'>"
            f"<div class='dt-head'>{head}</div>" + "".join(body) + "</div>")


def _facts(pairs: list) -> str:
    """A drill-down body as labelled fields, not a run-on sentence."""
    if not pairs:
        return ""
    cells = "".join(
        f"<div class='fact'><span class='fl'>{html.escape(label)}</span>"
        f"<span class='fv'>{value}</span></div>" for label, value in pairs)
    return f"<div class='dt-facts'>{cells}</div>"


def _group_ends(n: int, groups: list | None) -> set:
    """Column indices (0-based) that end a conceptual group, given `groups`
    (a list of group sizes summing to `n`) -- or every-but-last index when
    `groups` is None (no grouping requested)."""
    if not groups:
        return set()
    ends, i = set(), -1
    for size in groups:
        i += size
        ends.add(i)
    ends.discard(n - 1)         # the last column never needs a trailing gap
    return ends


_TAG_RE = re.compile(r"<[^>]+>")


def _text_len(html_str) -> int:
    """Visible character count of an HTML snippet (strips tags/entities),
    for sizing a column to what it actually displays -- e.g. a portrait
    `<span>` + badge markup around "Jonathan Taylor" must not count the
    markup itself as "content", or every player-name column would measure
    as absurdly wide."""
    if not html_str:
        return 0
    t = _TAG_RE.sub("", str(html_str))
    t = html.unescape(t)
    return len(t)


def _cell_width(html_str) -> float:
    """Rendered width of a data cell in `ch`, = its visible text length
    plus an allowance for the non-text furniture the markup carries that
    `_text_len` (deliberately) drops. A `.pface`/`.face` portrait is a real
    ~20px disc + 6px margin (~4ch) and the `.posrank` badge adds ~6px
    margin + padding + border beyond its own text (~1.5ch); without this,
    a "portrait + name + POS #rank" Player cell measures ~5ch short of
    what it needs and the name clips to an ellipsis under
    `table-layout:fixed`."""
    if not html_str:
        return 0.0
    s = str(html_str)
    extra = 4.0 * len(re.findall(r"class=['\"][^'\"]*\bp?face\b", s))
    extra += 1.5 * len(re.findall(r"\bposrank\b", s))
    return _text_len(s) + extra


def _content_widths(cols: list, rows: list) -> list:
    """Real per-column width in `ch` units (≈ the width of "0" in the
    table's own font), from the ACTUAL max content length in that column
    across the header label and every row -- not a hand-picked weight.
    This is what "columns sized by content" means literally: measure it,
    don't guess it.

    `rows` is either `_mini_table`'s `[[(html, is_num), ...], ...]` or
    `_mini_table_rows`'s `[([(html, is_num), ...], row_class), ...]`; both
    shapes are handled since callers pass whichever they have.

    The header gets its own, slightly larger per-character factor than the
    data cells: `th` here renders `text-transform:uppercase` +
    `letter-spacing:.06em`, which widens the rendered text past its raw
    character count (verified: "Margin" at a plain `+1.5ch` buffer clipped
    to "MARG…"). But the factor has to stay MODEST -- an over-large one
    (1.35x + 2.5 flat) inflates every multi-word header ("Share of pos" ->
    18.5ch) so far past what it needs that the table's measured width
    blows past the panel, `table-layout:fixed` scales every column DOWN to
    compensate, and the widest data column (Player, portrait + name + POS
    #rank) is the one that visibly clips. `.06em` letter-spacing + an
    uppercase-vs-mixed-case allowance is about 1.22x, plus a small flat
    buffer. Data cells get no transform; they measure via `_cell_width`
    (text + portrait/badge furniture) and only need breathing room.
    Floor of 2 so a single-character column ("W"/"L") still gets a sane
    minimum box.
    """
    n = len(cols)
    head_w = [_text_len(c) for c, _ in cols]
    data_w = [0.0] * n
    for r in rows:
        cells = r[0] if r and isinstance(r[0], list) else r
        for i, (v, _num) in enumerate(cells[:n]):
            data_w[i] = max(data_w[i], _cell_width(v))
    return [max(h * 1.22 + 2, d + 1.5, 2)
            for h, d in zip(head_w, data_w)]


def _spaced_cols(cols: list, groups: list | None, rows: list,
                 widths: list | None = None):
    """Interleaves a real, empty spacer column after each group boundary
    (every index `_group_ends` marks) so column grouping is an actual gap
    in the table, not cell padding.

    Under `table-layout:fixed`, a `<col>`'s width is fixed and a cell's own
    `padding` does not push the FOLLOWING column rightward -- it only
    shifts that cell's own content within its already-fixed box, so no
    amount of `padding-right` can open real space between two columns.
    Real columns are sized to their ACTUAL content (`_content_widths`,
    measured in `ch` -- roughly one character wide -- unless `widths`
    overrides it). Group separation is a genuine empty column with its own
    small fixed `ch` width (`_GAP_CH`); under `table-layout:fixed` the
    table's `width:100%` leftover is distributed PROPORTIONALLY across
    every column with a width, so the real columns keep their relative
    sizing and the spacers stay a modest gap. (Leaving the spacers
    width-less made them the ONLY things absorbing leftover space, so with
    content-tight real columns the spacers swallowed most of the table and
    squeezed every real column -- see `_colgroup`.)

    Returns `(widths2, is_gap)` -- `widths2` carries each real column's `ch`
    width and each spacer's own fixed `ch` width (`_GAP_CH`); `is_gap[i]`
    marks which entries are spacers so callers can render an empty
    `<col>`/`<td>` there instead of a real header/cell.
    """
    if not widths:
        widths = _content_widths(cols, rows)
    ends = _group_ends(len(cols), groups)
    widths2, is_gap = [], []
    for i, w in enumerate(widths):
        widths2.append(w)
        is_gap.append(False)
        if i in ends:
            widths2.append(_GAP_CH)
            is_gap.append(True)
    return widths2, is_gap


# Width of a group-separator spacer column, in `ch`. Small enough to read as
# a gap, not a whole empty column.
_GAP_CH = 3.0


# Per-column right padding on `dt-games-compact` cells, in `ch` (see `_CSS`'s
# `padding-right:10px` -- ~0.55ch per px at the table's 12.5px font). Added
# into the min-width total so the reserve accounts for cell padding too.
_PAD_CH = 1.5


def _colgroup(widths: list, is_gap: list) -> str:
    """`<colgroup>` for `table-layout:fixed` from an already-expanded
    per-position `ch`-unit width list (real columns + any spacer columns).

    Every `<col>` -- real AND spacer -- gets an explicit `ch` width. The
    table carries `width:100%`, and the `ch` widths will almost never sum
    to exactly that; under `table-layout:fixed` the browser distributes the
    leftover space PROPORTIONALLY across every column that has a width, so
    real columns keep their relative sizing and the spacers stay a small
    fraction of the table (a visible gap, not a whole empty column).

    An earlier version gave spacers NO width so `table-layout:fixed` would
    funnel ALL the leftover into them -- but with content-measured real
    columns summing well under 100%, that meant the spacers alone absorbed
    the majority of the table width, squeezing every real column and
    clipping headers ("MARGIN" -> "MARG..."). Giving the spacers their own
    fixed `ch` (`_GAP_CH`) puts them back in the proportional pool.
    """
    cols = "".join(f"<col style='width:{w:.2f}ch'>" for w in widths)
    return f"<colgroup>{cols}</colgroup>"


def _min_width_ch(widths: list) -> float:
    """The floor width a compact table may shrink to before its wrapper
    scrolls -- the sum of every column's measured `ch` (real + gap) plus a
    per-column padding reserve. Below this the table would have to clip a
    cell to fit, so it stops shrinking and `.dt-block` scrolls instead."""
    return sum(widths) + _PAD_CH * len(widths)


def _mini_table(cols: list, rows: list, groups: list | None = None,
                widths: list | None = None) -> str:
    """A compact table for inside a drill-down body.

    `cols` is [(label, is_num)], `rows` is [[(html, is_num), …]]. Carries
    `dt-games-compact` (tighter cell padding, see `_CSS`) -- unlike
    `_lineup_mini`'s fixed 3-column slot/name/points table, this one's
    column count varies by caller (4-6 columns), so the base `dt-games`
    padding (sized for 2-3 wide columns) reads as loose gaps once there are
    this many.

    `groups` (optional): column-count sizes for conceptual clusters (e.g.
    `[1, 3, 1, 1]` for Player | Starts+PPG+Pts | Share | Bench) -- a real
    empty spacer column (see `_spaced_cols`) is inserted after every group
    but the last, so related figures sit close together and unrelated ones
    read as genuinely separate. `widths` (optional): relative weight per
    real column, sized to what that column actually holds (defaults to `2`
    for a text column, `1` for numeric) -- these are real column widths,
    not grouping hints; grouping itself comes entirely from the spacer.
    """
    if not rows:
        return ""
    widths2, is_gap = _spaced_cols(cols, groups, rows, widths)
    colgroup = _colgroup(widths2, is_gap)
    cells_iter = iter(cols)
    head_parts = []
    for gap in is_gap:
        if gap:
            head_parts.append("<th class='gap-col'></th>")
        else:
            c, num = next(cells_iter)
            head_parts.append(f"<th class='{'n' if num else ''}'>"
                              f"{html.escape(c)}</th>")
    head = "".join(head_parts)
    body_parts = []
    for r in rows:
        row_iter = iter(r)
        tds = []
        for gap in is_gap:
            if gap:
                tds.append("<td class='gap-col'></td>")
            else:
                v, num = next(row_iter)
                tds.append(f"<td class='{'n' if num else ''}'>{v}</td>")
        body_parts.append("<tr>" + "".join(tds) + "</tr>")
    mw = _min_width_ch(widths2)
    return (f"<table class='dt-games dt-games-compact' "
            f"style='min-width:{mw:.1f}ch'>{colgroup}"
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_parts)}"
            f"</tbody></table>")


def _mini_table_rows(cols: list, rows: list, groups: list | None = None,
                     widths: list | None = None) -> str:
    """`_mini_table` where each row is `(cells, row_class)` -- lets a row carry
    the gold `.bench-impact` highlight. Same `dt-games-compact` padding,
    `groups` and `widths` support (see `_mini_table`/`_spaced_cols`)."""
    if not rows:
        return ""
    widths2, is_gap = _spaced_cols(cols, groups, rows, widths)
    colgroup = _colgroup(widths2, is_gap)
    cells_iter = iter(cols)
    head_parts = []
    for gap in is_gap:
        if gap:
            head_parts.append("<th class='gap-col'></th>")
        else:
            c, num = next(cells_iter)
            head_parts.append(f"<th class='{'n' if num else ''}'>"
                              f"{html.escape(c)}</th>")
    head = "".join(head_parts)
    parts = []
    for r, rc in rows:
        row_iter = iter(r)
        tds = []
        for gap in is_gap:
            if gap:
                tds.append("<td class='gap-col'></td>")
            else:
                v, num = next(row_iter)
                tds.append(f"<td class='{'n' if num else ''}'>{v}</td>")
        cls = f" class='{rc}'" if rc else ""
        parts.append(f"<tr{cls}>{''.join(tds)}</tr>")
    mw = _min_width_ch(widths2)
    return (f"<table class='dt-games dt-games-compact' "
            f"style='min-width:{mw:.1f}ch'>{colgroup}"
            f"<thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(parts)}</tbody></table>")


def _labeled(label: str, inner: str) -> str:
    """A small captioned block, for side-by-side tables inside a drill body."""
    if not inner:
        return ""
    return (f"<div class='dt-block'><div class='dt-sub'>{html.escape(label)}</div>"
            f"{inner}</div>")


def _boxed(inner: str) -> str:
    """A `.dt-block` with no caption -- just enough to keep a single mini-table
    from being a DIRECT child of `.dt-detail`, which triggers the site's
    global "wide Roster-tab listing" rule (width:100% + big cell padding,
    meant for a full-panel table, not a narrow drill mini-table)."""
    return f"<div class='dt-block'>{inner}</div>" if inner else ""


def _lineup_mini(df, ranks: dict | None = None, first_col: str = "slot",
                 swap_ids: set | None = None) -> str:
    """One lineup as a compact table, the way `_lineupmacro.html` renders it:
    slot (or position), portrait + name + `POS #rank`, points. A row whose
    player_id is in `swap_ids` gets the gold `.bench-impact` highlight -- a
    started player the optimal lineup drops, or a bench player it would start.
    """
    if df is None or not len(df):
        return ""
    head = ("<thead><tr><th></th><th>Player</th>"
            "<th class='n'>Pts</th></tr></thead>")
    body = []
    for _, x in df.iterrows():
        pid = x.get("player_id")
        pos = x.get("position", "")
        badge = _rank_badge(pos, _rank_of(ranks, pid))
        hot = (" class='bench-impact'"
               if swap_ids and pid is not None and str(pid) in swap_ids else "")
        body.append(
            f"<tr{hot}><td><span class='q'>{html.escape(str(x.get(first_col, '')))}"
            f"</span></td><td>{_pface(pid, pos)}"
            f"<strong>{html.escape(str(x['player_name']))}</strong>{badge}</td>"
            f"<td class='n'>{float(x['points']):.1f}</td></tr>")
    return (f"<table class='dt-games nosort'>{head}"
            f"<tbody>{''.join(body)}</tbody></table>")


def _fact_player(name, pos, pts: str, note: str = "", pid=None,
                 ranks: dict | None = None) -> str:
    """A player fact field: portrait + name + rank badge on one line, then the
    figure (and any note) on a second, so it reads as a labelled record rather
    than a run-on. The `POS #rank` badge sits right after the name (like the
    Draft-finds table); the bare position label is only shown as a fallback
    when there's no rank to badge, so the two never double up.
    """
    badge = _rank_badge(pos, _rank_of(ranks, pid))
    tag = badge or (f"<span class='pos'>{html.escape(str(pos))}</span>" if pos
                    else "")
    note_html = f"<span class='fnote'>{note}</span>" if note else ""
    return (f"<span class='fpl'>{_pface(pid, pos)}"
            f"<strong>{html.escape(str(name))}</strong>{tag}</span>"
            f"<span class='fnum'><span class='pts'>{pts}</span>{note_html}</span>")


def _player_fact(r, note: str = "", ranks: dict | None = None) -> str:
    """A player row (player_name/position/points[/player_id]) as a fact field."""
    return _fact_player(r["player_name"], r["position"],
                        f"{float(r['points']):.1f}", note,
                        pid=r.get("player_id") if hasattr(r, "get") else None,
                        ranks=ranks)


def _mgr_trade_ids(s: Season, rid, direction: str = "add") -> set:
    """player_ids this roster acquired ("add") or gave up ("drop") in a trade.

    The transactions frame is the only place the *direction* of a trade
    survives -- trade_performance deliberately drops it so both sides of a deal
    show on the league-wide chart.
    """
    tx = getattr(s, "transactions", None)
    if rid is None or tx is None or not {
            "type", "transaction", "roster_id",
            "player_id"}.issubset(getattr(tx, "columns", [])):
        return set()
    t = tx[(tx["type"] == "trade") & (tx["transaction"] == direction)
           & (tx["roster_id"] == rid)]
    if "status" in tx.columns:
        t = t[t["status"] != "failed"]
    return set(t["player_id"].astype(str))


# FAAB bids per (manager, player), for the "Cost" column. `settings.waiver_bid`
# rides on every raw Sleeper waiver claim but season._unnest_transactions drops
# it (adding it would be a parity change), so it is re-read here best-effort --
# the same webapp-only precedent app._waiver_bids / draft.py already set. Off
# the network the whole thing degrades to a plain "waiver" / "FA" label.
_report_waiver_bids: dict = {}


def _waiver_group_bids(s: Season) -> dict:
    """{(user_name, player_id str): total FAAB} spent acquiring that player."""
    ck = f"{s.league_id}:{s.season}"
    if ck not in _report_waiver_bids:
        bids: dict = {}
        try:
            from .api import sleeper_api
            for wk in range(1, int(getattr(s, "last_week_all", s.last_week)) + 1):
                for t in sleeper_api(
                        f"/league/{s.league_id}/transactions/{wk}"):
                    if t.get("type") != "waiver" or t.get("status") == "failed":
                        continue
                    bid = (t.get("settings") or {}).get("waiver_bid")
                    if bid is not None:
                        bids[str(t.get("transaction_id"))] = int(bid)
        except Exception:
            bids = {}
        _report_waiver_bids[ck] = bids
    bids = _report_waiver_bids[ck]
    tx = getattr(s, "transactions", None)
    out: dict = {}
    if not bids or tx is None or getattr(tx, "empty", True):
        return out
    names = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))
    w = tx[(tx["type"] == "waiver") & (tx["transaction"] == "add")]
    for row in w.itertuples():
        b = bids.get(str(row.transaction_id))
        if b is None:
            continue
        key = (names.get(row.roster_id, str(row.roster_id)), str(row.player_id))
        out[key] = out.get(key, 0) + b
    return out


def _deal_card(d: dict, ranks: dict | None = None) -> str:
    """One trade as the site's own `.deal` card (Transactions tab markup):
    a `.deal-meta` (week + winner/wash verdict) above a `.deal` article whose
    `.sides` list each team's `.plr` receipts -- portrait, name, POS #rank,
    who it came from (3+-team deal only), and points scored since.
    """
    sides = []
    for sd in d["sides"]:
        net = float(sd["net"])
        cls = "up" if net > 0 else "down" if net < 0 else ""
        rcls = "w" if net > 0 else "l" if net < 0 else ""
        players = sd.get("received_players") or []
        if players:
            plr = "".join(
                f"<div class='plr'><div class='plr-name'>"
                f"{_pface(p.get('player_id'), p.get('position'))}"
                f"<strong>{html.escape(str(p['player_name']))}</strong>"
                f"{_rank_badge(p.get('position'), _rank_of(ranks, p.get('player_id')))}"
                f"</div>"
                + (f"<div class='plr-from'><span class='q'>from "
                   f"{html.escape(str(p['from_team']))}</span></div>"
                   if d["n_teams"] > 2 and p.get("from_team") else "")
                + f"<div class='plr-pts'><span class='q'>"
                  f"{float(p['points']):.1f} pts since</span></div></div>"
                for p in players)
        else:
            plr = "<span class='q'>no players, picks or FAAB only</span>"
        sides.append(
            f"<div class='side {cls}'><div class='who'>"
            f"<span>{html.escape(str(sd['user_name']))}</span>"
            f"<span class='res {rcls}'>{net:+.0f}</span></div>"
            f"<div class='got'>{plr}</div></div>")
    if d.get("winner"):
        verdict_cls, verdict = "verdict", (
            f"<b>{html.escape(str(d['winner']))}</b> won it by {d['margin']:.0f}")
    else:
        verdict_cls, verdict = "verdict even", "a wash"
    tag = (f"<span class='tag deal-tag'>{d['n_teams']}-team</span>"
           if d["n_teams"] > 2 else "")
    return (f"<div class='deal-group'><div class='deal-meta'>"
            f"<span class='wk'>Week {d['week']}</span>"
            f"<span class='{verdict_cls}'>{verdict}</span></div>"
            f"<article class='deal'>{tag}<div class='sides'>"
            + "".join(sides) + "</div></article></div>")


def _mgr_transactions(s: Season, manager: str, ranks: dict | None = None) -> str:
    """One manager's season of dealing: trades as cards, then the waiver wire.

    Trades render as the site's own `.deal` cards (`metrics.trade_deals`,
    the same data the Transactions tab's cards use), filtered to deals this
    manager took part in. The waiver wire reads from `metrics.waiver_ledger`
    (the same ledger backing the Transactions tab's table -- pos_rank, PPG,
    starts, trend all come from there), filtered to this manager and topped
    up with the FAAB "Cost" ($N FAAB / FA), mirroring the Transactions tab.
    """
    rid = _mgr_roster_id(s, manager)
    if rid is None:
        return ""
    out = []

    try:
        deals = [d for d in metrics.trade_deals(s)
                 if any(sd["user_name"] == manager for sd in d["sides"])]
    except Exception:
        deals = []
    if deals:
        out.append("<p class='blurb'>Every trade they were part of, one card "
                   "per deal. Net is what the players they got scored for "
                   "them, minus what the players they gave up scored for the "
                   "other side.</p>")
        out.append("<div class='deals'>"
                   + "".join(_deal_card(d, ranks) for d in deals) + "</div>")

    try:
        wl = metrics.waiver_ledger(s, top_n=None)
        wl = wl[wl["user_name"] == manager].sort_values(
            "points", ascending=False) if len(wl) else wl
    except Exception:
        wl = None
    if wl is not None and len(wl):
        faab = _waiver_group_bids(s)
        pl = s.pl_wk
        have_pl = {"roster_id", "week", "player_id", "points",
                  "is_starter"}.issubset(getattr(pl, "columns", []))
        n_total = len(wl)
        shown = wl.head(15)
        wk_ranks_cache: dict = {}   # week -> week_position_ranks(s, week), shared
        # across every player's drill loop below since several pickups' stints
        # overlap the same weeks. Best-effort like every other network lookup
        # here: offline/uncached, the "Wk rank" column just reads an em dash.

        def _wk_ranks(wk):
            if wk not in wk_ranks_cache:
                try:
                    wk_ranks_cache[wk] = metrics.week_position_ranks(s, wk)
                except Exception:
                    wk_ranks_cache[wk] = {}
            return wk_ranks_cache[wk]
        waiver_rows = []
        for r in shown.itertuples():
            pid = str(r.player_id)
            bid = faab.get((manager, pid))
            kinds = str(r.via).split("/")
            if bid is not None:
                cost = f"${bid} FAAB" + (" / FA" if "FA" in kinds else "")
            elif "waiver" in kinds:
                cost = "waiver" + (" / FA" if "FA" in kinds else "")
            else:
                cost = "FA"
            again = f" <span class='q'>&times;{r.times}</span>" if r.times > 1 else ""
            badge = _rank_badge(r.position, r.pos_rank)
            cells = [
                (str(r.week), True),
                (f"{_pface(pid, r.position)}<strong>"
                 f"{html.escape(str(r.player_name))}</strong>{again}{badge}",
                 False),
                (html.escape(str(r.position)), False),
                (f"<span class='q'>{html.escape(cost)}</span>", False),
                (f"{int(r.starts)}", True),
                (f"{r.points:.0f}", True)]
            detail = ""
            if have_pl:
                wks = pl[(pl["roster_id"] == rid)
                        & (pl["player_id"].astype(str) == pid)].sort_values("week")
                if not wks.empty:
                    total = float(r.points) or 1.0
                    started_wks = wks[wks["is_starter"]]
                    best_w = (int(started_wks.loc[started_wks["points"].idxmax(),
                                                  "week"])
                             if len(started_wks) else None)
                    worst_w = (int(started_wks.loc[started_wks["points"].idxmin(),
                                                   "week"])
                              if len(started_wks) > 1 else None)
                    running, wk_rows = 0.0, []
                    for _, x in wks.iterrows():
                        wk = int(x["week"])
                        started = bool(x.get("is_starter"))
                        if started:
                            running += float(x["points"])
                        # A missing entry here means the player has NO real
                        # NFL stat line for the week at all (bye/inactive) --
                        # not that he was benched, which still has a real
                        # rank (week_position_ranks is read unconditionally,
                        # regardless of started/bench status).
                        wrk = _wk_ranks(wk).get(pid)
                        rank_txt = (f"{r.position} #{wrk['rank']}" if wrk
                                   else "DNP")
                        share = f"{float(x['points']) / total * 100:.0f}%"
                        hl = ("bench-impact" if started and
                              wk in (best_w, worst_w) else "")
                        wk_rows.append(([
                            (f"{wk}", True),
                            ("started" if started
                             else "<span class='q'>bench</span>", False),
                            (f"{float(x['points']):.1f}", True),
                            (f"{running:.1f}" if started else
                             "<span class='q'>&ndash;</span>", True),
                            (f"<span class='q'>{share}</span>", True),
                            (f"<span class='q'>{rank_txt}</span>", True)],
                            hl))
                    detail = _boxed(_mini_table_rows(
                        [("Wk", True), ("Role", False), ("Pts", True),
                         ("Points to date", True), ("Share", True),
                         ("Wk rank", True)], wk_rows,
                        # Wk/Role (when, how) | Pts/Points to date (the
                        # scoring, running total through that week) |
                        # Share/Wk rank (context on that week). Widths are
                        # measured from actual content (_content_widths),
                        # not hand-picked -- a manual weight here claimed
                        # more room than the real text needed.
                        groups=[2, 2, 2]))
            waiver_rows.append((cells, detail))
        more = f" Showing the top 15 of {n_total}." if n_total > 15 else ""
        out.append(f"<p class='blurb'>Waiver &amp; free-agent pickups, by what "
                   f"they returned while rostered.{more}</p>")
        out.append(_drill_table(
            [("Wk", True), ("Player", False), ("Pos", False), ("Cost", False),
             ("Starts", True), ("Pts", True)],
            "minmax(40px,0.5fr) minmax(220px,2.2fr) minmax(50px,0.6fr) "
            "minmax(70px,1fr) minmax(56px,0.7fr) minmax(60px,0.8fr)",
            waiver_rows,
            # Wk alone | Player+Pos (identity) | Cost alone | Starts+Pts
            # (the return).
            groups=[1, 2, 1, 2]))
    return "".join(out)


def _mgr_standouts(s: Season, manager: str,
                   ranks: dict | None = None) -> tuple[str, str]:
    """Who carried the team all season, and the best moves off waivers / trades.

    Returns `(moves_html, players_html)` -- two INDEPENDENT blocks the caller
    renders as separate objects under one "Season standouts" heading: the
    headline moves (Season MVP / Best pickup / Best trade add) as plain
    `_facts`, and the season-long player drill table. They are not wrapped
    or boxed together.
    """
    from . import draft as _draft

    rid = _mgr_roster_id(s, manager)
    pl = s.pl_wk
    facts, table = [], ""
    if rid is not None and {"roster_id", "is_starter", "player_name",
                            "position", "points"}.issubset(pl.columns):
        d = pl[(pl["roster_id"] == rid) & pl["is_starter"]]
        if not d.empty:
            have_id = "player_id" in d.columns
            keys = ["player_name", "position"] + (["player_id"] if have_id else [])
            g = (d.groupby(keys, as_index=False)["points"].sum()
                 .sort_values("points", ascending=False))
            top = g.iloc[0]
            facts.append(("Season MVP", _fact_player(
                top["player_name"], top["position"], f"{top['points']:.0f} pts",
                pid=top.get("player_id"), ranks=ranks)))
            # Each leader drills into how those points were actually accumulated;
            # portrait + POS #rank + a PPG column, like the Roster tab. The
            # per-week table carries the whole stint (started weeks and any
            # weeks the player sat), a running Total, and marks the best / worst
            # started week with the same gold row highlight the lineup tables
            # use for a swap.
            allrows = (pl[(pl["roster_id"] == rid)]
                       if {"roster_id", "week", "is_starter"}.issubset(pl.columns)
                       else pl.iloc[0:0])
            # Trend sparkline (the Draft-finds convention): weekly output
            # graded against the position's own replacement level, spanning
            # the whole season regardless of started/benched.
            try:
                repl = _draft._replacement_level(s, ranks or {})
                span = max(s.last_week_all, 1)
            except Exception:
                repl, span = {}, 1
            wk_ranks_cache: dict = {}

            def _wk_ranks(wk):
                if wk not in wk_ranks_cache:
                    try:
                        wk_ranks_cache[wk] = metrics.week_position_ranks(s, wk)
                    except Exception:
                        wk_ranks_cache[wk] = {}
                return wk_ranks_cache[wk]

            top12 = g.head(12)
            try:
                trends = _draft._season_trend(
                    s, [p for p in top12.get(
                        "player_id", pd.Series(dtype=object)) if pd.notna(p)])
            except Exception:
                trends = {}

            drows = []
            for r in top12.itertuples():
                pid = getattr(r, "player_id", None)
                starts = (d[d["player_id"] == pid] if have_id
                          else d[d["player_name"] == r.player_name])
                stint = (allrows[allrows["player_id"] == pid]
                         if have_id and len(allrows)
                         else starts).sort_values("week")
                nst = max(len(starts), 1)
                total_pts = float(stint["points"].sum()) if len(stint) else \
                    float(r.points)
                weeks_n = stint["week"].nunique() if len(stint) else len(starts)
                # Bench pts = the gap between Total and Started -- what they
                # scored on THIS roster in weeks they sat, not the optimal-
                # lineup-derived "left on bench" figure Week by week shows
                # (this is real points scored while benched, not a missed
                # opportunity cost). bench_weeks/bench_ppg use their own
                # denominator (weeks actually benched), not the combined
                # weeks_n, same "rate scoped to the role" convention the
                # Roster tab's Starting PPG / Bench PPG columns use.
                bench_pts = max(total_pts - float(r.points), 0.0)
                bench_stint = (stint[~stint["week"].isin(starts["week"])]
                              if len(stint) else stint.iloc[0:0])
                bench_weeks = bench_stint["week"].nunique() if len(bench_stint) else 0
                bench_ppg = bench_pts / bench_weeks if bench_weeks else 0.0
                badge = _rank_badge(r.position, _rank_of(ranks, pid))
                trend = ""
                if pid is not None:
                    weekly = trends.get(str(pid), [])
                    ref = repl.get(r.position, 0.0) / span
                    trend = _spark_svg(_draft._sparkline(weekly, ref))
                cells = [
                    (f"{_pface(pid, r.position)}<strong>"
                     f"{html.escape(str(r.player_name))}</strong>{badge}", False),
                    (html.escape(str(r.position)), False),
                    (f"{weeks_n}", True),
                    (f"{r.points / nst:.1f}", True),
                    (f"{bench_ppg:.1f}", True),
                    (f"{r.points:.0f}", True),
                    (f"{bench_pts:.0f}", True),
                    (f"{total_pts:.0f}", True),
                    (trend, False)]
                detail = ""
                if not starts.empty:
                    best = starts.loc[starts["points"].idxmax()]
                    worst = starts.loc[starts["points"].idxmin()]
                    dfacts = [
                        ("Starts", f"<span class='pts'>{len(starts)}</span>"),
                        ("Avg per start",
                         f"<span class='pts'>{starts['points'].mean():.1f}</span>"),
                        ("Best week", f"<span class='pts'>{best['points']:.1f}</span> "
                                      f"<span class='q'>wk {int(best['week'])}</span>"),
                    ]
                    if len(starts) > 1:
                        dfacts.append((
                            "Quietest week",
                            f"<span class='pts'>{worst['points']:.1f}</span> "
                            f"<span class='q'>wk {int(worst['week'])}</span>"))
                    started_wks = set(starts["week"].astype(int))
                    bw, ww = int(best["week"]), int(worst["week"])
                    running, wk_rows = 0.0, []
                    for _, x in stint.iterrows():
                        wk = int(x["week"])
                        started = wk in started_wks
                        if started:
                            running += float(x["points"])
                        hl = ("bench-impact" if started and
                              (wk == bw or (wk == ww and len(starts) > 1))
                              else "")
                        # See the waiver-drill loop above: a missing entry
                        # means no real NFL stat line that week (DNP), not a
                        # bench-only rank suppression.
                        wrk = _wk_ranks(wk).get(str(pid)) if pid is not None else None
                        rank_txt = f"{r.position} #{wrk['rank']}" if wrk else "DNP"
                        share = (f"{float(x['points']) / total_pts * 100:.0f}%"
                                if total_pts else "&ndash;")
                        wk_rows.append(([
                            (f"{wk}", True),
                            ("started" if started
                             else "<span class='q'>bench</span>", False),
                            (f"{float(x['points']):.1f}", True),
                            (f"{running:.1f}" if started else
                             "<span class='q'>&ndash;</span>", True),
                            (f"<span class='q'>{share}</span>", True),
                            (f"<span class='q'>{rank_txt}</span>", True)],
                            hl))
                    wk_tbl = _mini_table_rows(
                        [("Wk", True), ("Role", False), ("Pts", True),
                         ("Points to date", True), ("Share", True),
                         ("Wk rank", True)], wk_rows,
                        # Wk/Role (when, how) | Pts/Points to date (the
                        # scoring, running total through that week) |
                        # Share/Wk rank (context on that week). Widths are
                        # measured from actual content (_content_widths),
                        # not hand-picked.
                        groups=[2, 2, 2])
                    detail = _facts(dfacts) + _boxed(wk_tbl)
                drows.append((cells, detail))
            table = _drill_table(
                # PPG columns cluster (Starting/Bench), then pts columns
                # cluster (Started/Bench/Total, the last being their sum).
                [("Player", False), ("Pos", False), ("Weeks", True),
                 ("Starting PPG", True), ("Bench PPG", True),
                 ("Started pts", True), ("Bench pts", True),
                 ("Total pts", True), ("Trend", False)],
                "minmax(220px,2.2fr) minmax(40px,0.6fr) minmax(46px,0.7fr) "
                "minmax(64px,0.9fr) minmax(60px,0.9fr) minmax(64px,0.9fr) "
                "minmax(60px,0.9fr) minmax(60px,0.9fr) minmax(60px,0.8fr)",
                drows,
                # Player+Pos | Weeks | Starting PPG+Bench PPG | Started
                # pts+Bench pts+Total pts | Trend.
                groups=[2, 1, 2, 3, 1])
    # Waiver rows are already per acquiring roster (the metric joins on
    # player_id + roster_id), so a row naming this manager is genuinely theirs.
    # Trade rows are NOT: trade_performance joins on player_id alone so both
    # sides of a deal appear, which is what the league-wide chart wants. Scoped
    # to one manager it has to be narrowed to what they actually acquired, or a
    # player they traded AWAY reads as their best add.
    trade_adds = _mgr_trade_ids(s, rid, "add")
    for label, fn, ids in (("Best pickup", metrics.waiver_performance, None),
                           ("Best trade add", metrics.trade_performance, trade_adds)):
        try:
            t = fn(s)
            t = t[t["user_name"] == manager]
            if ids is not None:
                t = t[t["player_id"].astype(str).isin(ids)]
        except Exception:
            t = None
        if t is not None and len(t):
            # `points` is this manager's own points while rostering the player;
            # `total` is the player's across every team that held them, so it
            # both ranks wrong and overstates the figure here.
            b = t.loc[t["points"].idxmax()]
            facts.append((label, _fact_player(
                b["player_name"], b["position"], f"{b['points']:.0f} pts",
                "while rostered", pid=b.get("player_id"), ranks=ranks)))
    return (_facts(facts) if facts else ""), table


def _spark_svg(t) -> str:
    """The Draft-finds Trend sparkline (`draft._sparkline()` output) as inline
    SVG: a dashed line at the position's replacement PPG, the connecting line
    green above / red below it. "" when there's nothing to draw."""
    if not t or not isinstance(t, dict) or not t.get("segs"):
        return ""
    segs = "".join(
        f"<line class='{'up' if seg['up'] else 'down'}' x1='{seg['x1']}' "
        f"y1='{seg['y1']}' x2='{seg['x2']}' y2='{seg['y2']}'></line>"
        for seg in t["segs"])
    return (f"<svg class='spark-line' viewBox='0 0 56 16' "
            f"preserveAspectRatio='none'><line class='spark-avg' x1='0' "
            f"y1='{t['avg_y']}' x2='56' y2='{t['avg_y']}'></line>{segs}</svg>")


def _steal_span(v) -> str:
    """A `pos_steal` / `pos_adj` value as a green/red `res` span, "" if missing."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    cls = "w" if v >= 0 else "l"
    return f"<span class='res {cls}'>{'+' if v >= 0 else ''}{int(round(v))}</span>"


def _mgr_draft(s: Season, manager: str,
               ranks: dict | None = None) -> tuple[str, str]:
    """One manager's draft class, laid out like the webapp Draft-finds table:
    Pick (round.pick, e.g. "3.02"), Player (portrait + POS #rank), Pos order
    ("RB #5"), Pos rank ("RB #3"), draft +/- (`pos_steal`), Weeks, PPG, Total
    pts, Pos-adj (`pos_adj`), Trend, sorted by pick number.

    Returns `(summary_html, table_html)` -- the Best pick / Biggest reach
    facts and the full draft table as two INDEPENDENT blocks the caller
    renders separately under one "Draft class" heading, not glued together.
    """
    from . import draft as _draft
    try:
        mine = _draft.drafted_players(s)
    except Exception:
        try:                                  # fallback for an older draft.py
            mine = _draft.draft_board(s)
        except Exception:
            return "", ""
    if getattr(mine, "empty", True) or "user_name" not in mine.columns:
        return "", ""
    mine = mine[mine["user_name"] == manager].sort_values("pick_no")
    if mine.empty:
        return "", ""
    key = "pos_steal" if "pos_steal" in mine.columns else "steal"
    best = mine.loc[mine[key].idxmax()]
    worst = mine.loc[mine[key].idxmin()]

    def _pick_str(r):
        p = getattr(r, "pick", None)
        if isinstance(p, str) and p:
            return p
        rnd = getattr(r, "round", None)
        pir = getattr(r, "pick_in_round", getattr(r, "draft_slot", None))
        return f"{int(rnd)}.{int(pir):02d}" if rnd is not None and pir is not None \
            else f"#{int(r.pick_no)}"

    def _row_total(row):
        for k in ("total", "points", "rostered_points"):
            if k in row.index and pd.notna(row[k]):
                return float(row[k])
        return 0.0

    def _pick_fact(row):
        return _fact_player(
            row["player_name"], row["position"], f"{_row_total(row):.0f} pts",
            f"pick {_pick_str(row)}", pid=row.get("player_id"), ranks=ranks)
    summ = _facts([("Best pick", _pick_fact(best)),
                   ("Biggest reach", _pick_fact(worst))])

    def _num(v, fmt="{:.0f}"):
        return fmt.format(v) if v is not None and pd.notna(v) else ""

    rows = []
    for r in mine.itertuples():
        pid = getattr(r, "player_id", None)
        pos = str(r.position)
        badge = _rank_badge(pos, _rank_of(ranks, pid)) or \
            f"<span class='q'>{html.escape(pos)}</span>"
        pos_pick = getattr(r, "pos_pick_rank", None)
        pos_rk = getattr(r, "pos_rank", None)
        order_txt = (f"{pos} #{int(pos_pick)}"
                     if pos_pick is not None and pd.notna(pos_pick) else "")
        posrk_txt = (f"{pos} #{int(pos_rk)}"
                     if pos_rk is not None and pd.notna(pos_rk) else "N/A")
        total = next((float(getattr(r, k)) for k in
                      ("total", "points", "rostered_points")
                      if hasattr(r, k) and pd.notna(getattr(r, k))), 0.0)
        rows.append(
            f"<tr><td class='rank' data-sort='{int(r.pick_no):07d}'>"
            f"{html.escape(_pick_str(r))}</td>"
            f"<td class='name'>{_pface(pid, pos)}"
            f"{html.escape(str(r.player_name))}{badge}</td>"
            f"<td class='n'>{html.escape(order_txt)}</td>"
            f"<td class='n'>{html.escape(posrk_txt)}</td>"
            f"<td class='n'>{_steal_span(getattr(r, 'pos_steal', getattr(r, 'steal', None)))}</td>"
            f"<td class='n'>{_num(getattr(r, 'weeks', None))}</td>"
            f"<td class='n'>{_num(getattr(r, 'ppg', None), '{:.1f}')}</td>"
            f"<td class='n'>{total:.0f}</td>"
            f"<td class='n'>{_steal_span(getattr(r, 'pos_adj', None))}</td>"
            f"<td>{_spark_svg(getattr(r, 'trend', None))}</td></tr>")
    table = ("<table class='teams draftfinds'><thead><tr><th>Pick</th>"
             "<th>Player</th><th class='n'>Pos order</th><th class='n'>Pos rank</th>"
             "<th class='n'>draft +/&minus;</th><th class='n'>Weeks</th>"
             "<th class='n'>PPG</th><th class='n'>Total pts</th>"
             "<th class='n'>Pos-adj</th><th>Trend</th></tr></thead><tbody>"
             + "".join(rows) + "</tbody></table>")
    return summ, table


def _rivalry_games(uid, seasons: dict) -> dict:
    """{opponent user_id: [(season, week, pf, pa, result), …]} for one manager."""
    games: dict = {}
    for ss in seasons.values():
        um = ss.user_map
        rr = um[um["user_id"] == uid]
        tw = ss.team_wk
        if rr.empty or not {"roster_id", "opp", "points", "pa", "result",
                            "week"}.issubset(tw.columns):
            continue
        rid = rr.iloc[0]["roster_id"]
        opp_uid = dict(zip(um["roster_id"], um["user_id"]))
        mine = tw[(tw["roster_id"] == rid) & tw["result"].isin(["W", "L", "T"])]
        for _, g in mine.iterrows():
            ouid = opp_uid.get(g["opp"])
            if ouid is None:
                continue
            games.setdefault(ouid, []).append(
                (ss.season, int(g["week"]), float(g["points"]),
                 float(g["pa"]), str(g["result"])))
    return games


def _manager_avatars(s: Season) -> dict:
    """{user_name: avatar url} from the season's accounts frame, best-effort."""
    acc = getattr(s, "accounts", None)
    if acc is None or getattr(acc, "empty", True) or "user_name" not in acc.columns:
        return {}
    col = ("avatar_url" if "avatar_url" in acc.columns else
           "team_avatar_url" if "team_avatar_url" in acc.columns else None)
    if col is None:
        return {}
    return {r["user_name"]: r[col] for _, r in acc.iterrows()
            if isinstance(r["user_name"], str)}


def _mgr_rivalry(s: Season, manager: str, seasons: dict | None) -> str:
    """One manager's record vs each other manager, each row drilling to the games."""
    if not seasons:
        return ""
    try:
        h = metrics.head_to_head(seasons)
    except Exception:
        return ""
    h = h[(h["user_name"] == manager) & (h["games"] >= 1)]
    if h.empty:
        return ""
    uid_row = s.standings.loc[s.standings["user_name"] == manager, "user_id"]
    uid = uid_row.iloc[0] if len(uid_row) else None
    games = _rivalry_games(uid, seasons) if uid is not None else {}
    av = _manager_avatars(s)

    def _opp(nm):
        """Opponent name with their account avatar, matching the Career tab."""
        return f"{_face(av.get(nm))}{html.escape(str(nm))}"
    parts = []
    strong = h[h["games"] >= 2]
    if len(strong):
        own = strong.loc[strong["win_pct"].idxmax()]
        nem = strong.loc[strong["win_pct"].idxmin()]
        if own["opp_name"] != nem["opp_name"]:
            parts.append(_facts([
                ("Owns", f"{_opp(own['opp_name'])} "
                         f"<span class='pts'>{int(own['wins'])}-{int(own['losses'])}"
                         f"</span> <span class='q'>{own['win_pct']:.0f}%</span>"),
                ("Haunted by", f"{_opp(nem['opp_name'])} "
                               f"<span class='pts'>{int(nem['wins'])}-"
                               f"{int(nem['losses'])}</span> "
                               f"<span class='q'>{nem['win_pct']:.0f}%</span>"),
            ]))
    rows = []
    for r in h.sort_values("win_pct", ascending=False).itertuples():
        rec = f"{int(r.wins)}-{int(r.losses)}" + (f"-{int(r.ties)}" if r.ties else "")
        # gl is sorted (season, week, ...) ascending, so its last entry is
        # the most recent meeting -- shown as the drilldown's own last row,
        # not duplicated as a main-row column.
        gl = sorted(games.get(r.opp_user_id, []))
        cells = [(_opp(r.opp_name), False), (rec, False),
                 (f"{r.win_pct:.0f}%", True), (f"{r.margin:+.1f}", True)]
        det = ""
        if gl:
            grows = [
                [(str(yr), False), (str(wk), True), (f"{pf:.1f}", True),
                 (f"{pa:.1f}", True), (f"{pf - pa:+.1f}", True),
                 (f"<span class='res "
                  f"{'w' if res == 'W' else 'l' if res == 'L' else ''}'>"
                  f"{res}</span>", True)]
                for yr, wk, pf, pa, res in gl]
            det = _boxed(_mini_table(
                [("Season", False), ("Wk", True), ("PF", True), ("PA", True),
                 ("Margin", True), ("Result", True)], grows,
                # Season/Wk (when) | PF/PA/Margin (the score) | Result.
                # Result is a short W/L badge, not a number to line up with
                # PF/PA/Margin's decimals -- marked numeric (True) purely to
                # get the same right-alignment (table.dt-games td.n), so it
                # sits flush against the table's true right edge instead of
                # floating left in a wide, mostly-empty last column. Widths
                # are measured from actual content (_content_widths), not
                # hand-picked.
                groups=[2, 3, 1]))
        rows.append((cells, det))
    table = _drill_table(
        [("Opponent", False), ("Record", False), ("Win %", True), ("Avg margin", True)],
        "minmax(150px,2fr) minmax(80px,1fr) minmax(60px,0.8fr) "
        "minmax(80px,1fr)", rows)
    return "".join(parts) + table


def _mgr_splits(s: Season, manager: str) -> str:
    """The season sliced: awards, best/worst games, close-game and top-half splits."""
    rid = _mgr_roster_id(s, manager)
    tw = s.team_wk
    if rid is None or not {"roster_id", "points", "result", "pa", "week"}.issubset(tw.columns):
        return ""
    mine = tw[tw["roster_id"] == rid]
    dec = mine[mine["result"].isin(["W", "L"])]
    stats = []
    st = s.standings[s.standings["user_name"] == manager]
    if len(st):
        stats.append(("Weekly high scorer", f"{int(st.iloc[0]['highs'])}×"))
    lows = sum(1 for _, g in tw.groupby("week")
               if len(g) and g.loc[g["points"].idxmin(), "roster_id"] == rid)
    stats.append(("Weekly low scorer", f"{lows}×"))
    wins, losses = dec[dec["result"] == "W"], dec[dec["result"] == "L"]
    if len(wins):
        w = wins.loc[(wins["points"] - wins["pa"]).idxmax()]
        stats.append(("Biggest win", f"+{w['points'] - w['pa']:.1f} (wk {int(w['week'])})"))
    if len(losses):
        l = losses.loc[(losses["points"] - losses["pa"]).idxmin()]
        stats.append(("Worst loss", f"{l['points'] - l['pa']:.1f} (wk {int(l['week'])})"))
    close = dec[(dec["points"] - dec["pa"]).abs() < 10]
    if len(close):
        stats.append(("One-score games (<10)",
                      f"{int((close['result'] == 'W').sum())}-{int((close['result'] == 'L').sum())}"))
    if "opp" in dec.columns:
        n = len(s.standings)
        half = set(s.standings.sort_values("final_position").head(max(n // 2, 1))["roster_id"])
        vs = dec[dec["opp"].isin(half)]
        if len(vs):
            stats.append(("Vs the top half",
                          f"{int((vs['result'] == 'W').sum())}-{int((vs['result'] == 'L').sum())}"))
    lu = s.lineup
    if "user_name" in lu.columns:
        lu = lu[lu["user_name"] == manager]
        if len(lu):
            stats.append(("Points left on bench", f"{lu['left_on_bench'].sum():.0f}"))
            w = lu.loc[lu["left_on_bench"].idxmax()]
            stats.append(("Worst benching", f"{w['left_on_bench']:.0f} (wk {int(w['week'])})"))
    if not stats:
        return ""
    rows = "".join(f"<tr><td class='name'>{k}</td><td class='n'>{v}</td></tr>"
                   for k, v in stats)
    return ("<table class='teams'><thead><tr><th>Split</th><th class='n'>Value</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table>")


def _mgr_roster_id(s: Season, manager: str):
    m = s.user_map.loc[s.user_map["user_name"] == manager, "roster_id"]
    return None if m.empty else m.iloc[0]


def _game_log(s: Season, manager: str, ranks: dict | None = None) -> str:
    """One manager's season game by game, each week drilling into their lineup.

    Mirrors the webapp Roster -> Efficiency section: a Lineup % column on the
    row, and a Started | Bench drill-down where a gold row on either side marks
    a player the best legal lineup would have swapped (a started player it drops,
    a bench player it starts).
    """
    rid = _mgr_roster_id(s, manager)
    tw = s.team_wk
    # A column-less empty frame (the test fixture) has no "roster_id" to select.
    if rid is None or not {"roster_id", "week", "points"}.issubset(tw.columns):
        return ""
    name = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))
    mine = tw[tw["roster_id"] == rid].sort_values("week")
    if mine.empty:
        return ""
    pl = s.pl_wk
    have_pl = {"roster_id", "week", "is_starter", "player_name", "points",
               "position"}.issubset(pl.columns)
    lu = s.lineup if "user_name" in getattr(s.lineup, "columns", []) else None
    rows = []
    for _, r in mine.iterrows():
        wk = int(r["week"])
        opp = name.get(r["opp"]) if pd.notna(r.get("opp")) else None
        res = str(r["result"]) if pd.notna(r.get("result")) else "N/A"
        cls = {"W": "w", "L": "l"}.get(res, "")
        pa = r.get("pa")
        pa_txt = f"{pa:.1f}" if pd.notna(pa) else "N/A"
        mg_txt = f"{r['points'] - pa:+.1f}" if pd.notna(pa) else "N/A"
        # Lineup %: started points as a share of the best legal lineup, the same
        # per-week read the Efficiency table shows.
        eff_txt = "N/A"
        opt_val = None
        if lu is not None:
            lr = lu[(lu["user_name"] == manager) & (lu["week"] == wk)]
            if len(lr) and float(lr.iloc[0]["optimal"]) > 0:
                opt_val = float(lr.iloc[0]["optimal"])
                eff_txt = f"{float(r['points']) / opt_val * 100:.0f}%"
        cells = [
            (str(wk), False),
            (html.escape(str(opp)) if opp else "N/A (no game)", False),
            (f"<span class='res {cls}'>{res}</span>", False),
            (f"{r['points']:.1f}", True), (pa_txt, True), (mg_txt, True),
            (eff_txt, True)]
        # Per-week drill-down: labelled facts, then Started | Bench side by side.
        facts, lineup_tbl = [], ""
        wp = pl.iloc[0:0]
        if have_pl:
            wkall = pl[(pl["roster_id"] == rid) & (pl["week"] == wk)]
            wp = wkall[wkall["is_starter"]]
            bench = wkall[~wkall["is_starter"]]
            if not wp.empty:
                top = wp.loc[wp["points"].idxmax()]
                facts.append(("Top starter", _player_fact(top, ranks=ranks)))
                if len(wp) > 1:
                    cold = wp.loc[wp["points"].idxmin()]
                    facts.append(("Coldest starter", _player_fact(cold, ranks=ranks)))
            if not bench.empty:
                bh = bench.loc[bench["points"].idxmax()]
                if float(bh["points"]) > 0:
                    facts.append(("Best left on bench",
                                  _player_fact(bh, ranks=ranks)))
                # What the bench actually scored this week -- real points, not
                # the optimal-lineup opportunity cost the "Bench cost" fact
                # below shows; the two read very differently on a week where
                # the bench mostly scored zero but the one live optimal swap
                # would still have been small.
                bench_pts_wk = float(bench["points"].sum())
                facts.append(("Bench points",
                              f"<span class='pts'>{bench_pts_wk:.1f}</span>"))
        if lu is not None and len(lr):
            lrr = lr.iloc[0]
            facts.append(("Optimal lineup",
                          f"<span class='pts'>{lrr['optimal']:.1f}</span>"))
            facts.append(("Bench cost",
                          f"<span class='pts'>{lrr['left_on_bench']:.1f}</span> "
                          "<span class='q'>optimal vs started</span>"))
            # The stinger: a loss the best lineup would have won.
            if (pd.notna(pa) and float(r["points"]) < float(pa)
                    and float(lrr["optimal"]) > float(pa)):
                facts.append(("Coaching cost", "<span class='res l'>the optimal "
                              "lineup would have won this</span>"))
        if not wp.empty:
            ws = assign_slots(wp, s.slots)
            started_ids = set(wp["player_id"].astype(str))
            opt_ids: set = set()
            if s.slots and not wkall.empty:
                ol = optimal_lineup(wkall, s.slots)
                if len(ol):
                    opt_ids = set(ol["player_id"].astype(str))
            # Gold on either side: a starter the optimal lineup drops, a bench
            # player it starts (the same both-sides swap cue the Efficiency
            # drilldown uses).
            swap_started = {p for p in started_ids if p not in opt_ids}
            bench_all = wkall[~wkall["is_starter"]] if have_pl else pl.iloc[0:0]
            bench_view = bench_all.sort_values("points", ascending=False)
            swap_bench = {str(p) for p in bench_view["player_id"].astype(str)
                          if str(p) in opt_ids}
            started_tbl = _lineup_mini(ws, ranks, "slot", swap_started)
            bench_tbl = _lineup_mini(bench_view, ranks, "position", swap_bench)
            bench_cap = (f"Bench · {float(bench_view['points'].sum()):.1f} pts"
                        if len(bench_view) else "Bench")
            lineup_tbl = (
                "<div class='dt-tables'>"
                + _labeled(f"Started · {float(r['points']):.1f} pts", started_tbl)
                + (_labeled(bench_cap, bench_tbl) if bench_tbl else "")
                + "</div>")
        rows.append((cells, _facts(facts) + lineup_tbl))
    cols = [("Wk", False), ("Opponent", False), ("Result", False),
            ("PF", True), ("PA", True), ("Margin", True), ("Lineup %", True)]
    return _drill_table(
        cols, "minmax(34px,0.5fr) minmax(130px,1.6fr) minmax(56px,0.7fr) "
        "minmax(56px,0.7fr) minmax(56px,0.7fr) minmax(60px,0.8fr) "
        "minmax(60px,0.8fr)", rows)


def _position_mix(s: Season, manager: str, ranks: dict | None = None) -> str:
    """Where one manager's started points came from, by position + league rank.

    Deliberately started-only for Share/League rank (mirrors the site's own
    `position_scoring` chart) -- Bench pts rides along as a REFERENCE column
    only, never folded into the started totals those two columns rank on.
    """
    rid = _mgr_roster_id(s, manager)
    pl = s.pl_wk
    if rid is None or not {"roster_id", "is_starter", "position",
                           "points"}.issubset(pl.columns):
        return ""            # column-less empty frame (the test fixture)
    starters = pl[pl["is_starter"] & pl["position"].isin(metrics.POSITIONS)]
    if starters.empty:
        return ""
    by_team = starters.groupby(["roster_id", "position"], as_index=False)["points"].sum()
    by_team["rk"] = by_team.groupby("position")["points"].rank(ascending=False, method="min")
    n_teams = pl["roster_id"].nunique()
    mine = by_team[by_team["roster_id"] == rid]
    if mine.empty:
        return ""
    pts = dict(zip(mine["position"], mine["points"]))
    rk = dict(zip(mine["position"], mine["rk"]))
    total = float(sum(pts.values())) or 1.0
    have_id = "player_id" in starters.columns
    ours = starters[starters["roster_id"] == rid]
    # Bench pts is shown for REFERENCE only on this section -- Share/League
    # rank stay started-only (this section is deliberately scoped to started
    # points, mirroring the site's own position_scoring chart); bench_by_pos
    # is never folded into `pts`/`total`/`rk` above.
    bench_all = pl[(pl["roster_id"] == rid) & (~pl["is_starter"])
                   & pl["position"].isin(metrics.POSITIONS)]
    bench_by_pos = bench_all.groupby("position")["points"].sum().to_dict()
    rows = []
    for p in metrics.POSITIONS:
        if p not in pts:
            continue
        cells = [(p, False), (f"{pts[p]:.0f}", True),
                 (f"<span class='q'>{bench_by_pos.get(p, 0.0):.0f}</span>", True),
                 (f"{pts[p] / total * 100:.0f}%", True),
                 (_rank_pill(int(rk[p]), n_teams), True)]
        # Drill: who actually produced those points at this position, with the
        # portrait + POS #rank badge and a PPG column like the Roster tab.
        sub = ours[ours["position"] == p]
        bench_sub = bench_all[bench_all["position"] == p]
        detail = ""
        if not sub.empty:
            agg = {"pts": ("points", "sum"), "starts": ("points", "size")}
            keys = ["player_name"] + (["player_id"] if have_id else [])
            g2 = (sub.groupby(keys, as_index=False).agg(**agg)
                  .sort_values("pts", ascending=False).head(8))
            bench_pts_by_player = (bench_sub.groupby(keys)["points"].sum()
                                   if have_id else
                                   bench_sub.groupby("player_name")["points"].sum())
            drows = []
            for x in g2.itertuples():
                pid = getattr(x, "player_id", None)
                badge = _rank_badge(p, _rank_of(ranks, pid))
                bkey = (x.player_name, pid) if have_id else x.player_name
                bpts = float(bench_pts_by_player.get(bkey, 0.0))
                drows.append([
                    (f"{_pface(pid, p)}<strong>{html.escape(str(x.player_name))}"
                     f"</strong>{badge}", False),
                    (f"{int(x.starts)}", True),
                    (f"{x.pts / max(int(x.starts), 1):.1f}", True),
                    (f"{x.pts:.0f}", True),
                    (f"<span class='q'>{bpts:.0f}</span>", True),
                    (f"{x.pts + bpts:.0f}", True),
                    (f"{x.pts / (pts[p] or 1) * 100:.0f}%", True)])
            detail = _boxed(_mini_table(
                [("Player", False), ("Starts", True), ("PPG", True),
                 ("Pts", True), ("Bench pts", True), ("Total pts", True),
                 ("Share of pos", True)], drows,
                # Player alone | Starts/PPG (how often, at what rate) | Pts +
                # Bench pts adjacent (the two pieces) | Total pts right after
                # as their sum | Share of pos last, as relative context.
                # Widths are measured from actual content (_content_widths),
                # not hand-picked.
                groups=[1, 2, 2, 1, 1]))
        rows.append((cells, detail))
    return _drill_table(
        [("Position", False), ("Started pts", True), ("Bench pts", True),
         ("Share", True), ("League rank", True)],
        "minmax(70px,0.8fr) minmax(90px,1fr) minmax(70px,0.8fr) "
        "minmax(60px,0.7fr) minmax(100px,1.1fr)", rows,
        # Position alone | Started pts+Bench pts (the two pieces) |
        # Share+League rank (relative context).
        groups=[1, 2, 2])


# Chart key -> (plot function, what it takes). The keys match the web app's
# /chart/<key> endpoint, so the dashboard can render the same report sections as
# lazy <img> tags while the standalone file bakes them in as base64 PNGs.
#
# The kinds are "season", "seasons", "playoff" and "season+manager" -- the last
# takes (season, manager), which is why the app's /chart endpoint has to accept
# and forward a `manager` param. A key added here without that endpoint entry
# renders in the standalone file but 404s in the report tab.
_CHART_FNS = {
    "mgr_score_band": (plots.plot_mgr_score_band, "season+manager"),
    "mgr_optimal": (plots.plot_mgr_optimal, "season+manager"),
    "mgr_margins": (plots.plot_mgr_margins, "season+manager"),
    "standings": (plots.plot_standings, "season"),
    "power_rank": (plots.plot_power_rank, "season"),
    "allplay": (plots.plot_allplay, "season"),
    "luck": (plots.plot_luck, "season"),
    "efficiency": (plots.plot_efficiency, "season"),
    "consistency": (plots.plot_consistency, "season"),
    "pf_pa": (plots.plot_pf_pa, "season"),
    "table_position": (plots.plot_table_position, "season"),
    "team_points": (plots.plot_team_points, "season"),
    "position_scoring": (plots.plot_position_scoring, "season"),
    "roster_heatmap": (plots.plot_roster_heatmap, "season"),
    "flex_usage": (plots.plot_flex_usage, "season"),
    "manager_profile": (plots.plot_manager_profile, "season"),
    "trade_performance": (plots.plot_trade_performance, "season"),
    "waiver_performance": (plots.plot_waiver_performance, "season"),
    "career": (plots.plot_career, "seasons"),
    "trajectory": (plots.plot_trajectory, "seasons"),
    "bracket": (plots.plot_playoff_bracket, "playoff"),
    # Postseason, mirroring the webapp Playoffs tab. The "playoff_*" kinds
    # assemble the same single-season {season: obj} sub-dicts / consolation
    # inputs the app's /chart route builds by hand.
    "playoff_players_splice": (plots.plot_playoff_players_splice, "playoff_splice"),
    "consolation_bracket": (plots.plot_consolation_bracket, "consolation_bracket"),
    "consolation_players_splice": (plots.plot_consolation_players_splice,
                                   "consolation"),
    "consolation_clutch": (plots.plot_consolation_clutch, "consolation_clutch"),
}


def _consolation_of(s, p):
    """(consolation_bracket dict, reference_scores) for this season, best-effort."""
    try:
        from .playoffs import reference_scores, consolation_bracket
        return consolation_bracket(s, p), reference_scores(s)
    except Exception:
        return None, None


def _losers_bracket_of(s):
    """Sleeper's real losers_bracket as a playoff object, or None -- lets the
    consolation-bracket chart draw as a tree rather than ragged week columns."""
    try:
        from .playoffs import playoff, sleeper_losers_bracket
        cfg = sleeper_losers_bracket(s.league_id, s.season)
        return playoff(cfg, validate=False) if cfg else None
    except Exception:
        return None


def _chart_args(kind, s, seasons=None, playoffs=None, manager=None):
    """What a chart of this kind is called with, or None if unavailable here.

    A report that lacks a kind's input -- no career chain, no stored bracket for
    this season, no manager scope -- gets None and drops the panel, matching the
    best-effort contract everywhere else in the report.
    """
    if kind == "season":
        return (s,)
    if kind == "seasons":
        return (seasons,) if seasons else None
    if kind == "season+manager":
        return (s, manager) if manager else None
    p = (playoffs or {}).get(s.season)
    if kind == "playoff":
        if p is None:
            return None
        # The bracket chart also takes reference scores (for bye/idle nodes) and
        # the consolation bracket (its own games render in a separate chart; here it just
        # supplies the last-place name for the outcome caption); both best-effort.
        tb, ref = _consolation_of(s, p)
        return (p, ref, tb)
    if kind == "playoff_splice":
        # plot_playoff_players_splice(seasons, playoffs, ...) -- single-season
        # sub-dicts, championship path (scope defaults to "title"), same as the
        # webapp Playoffs tab's own "Best playoff players".
        if p is None:
            return None
        return ({s.season: s}, {s.season: p})
    if kind in ("consolation_bracket", "consolation", "consolation_clutch"):
        if p is None:
            return None
        tb, ref = _consolation_of(s, p)
        # A season where every team made the championship bracket has no
        # consolation bracket at all -- the plot functions would render a
        # titled-blank panel, but a standalone export shouldn't carry dead
        # panels, so drop them (best-effort, same as any other missing input).
        if not tb or not (tb.get("teams") or tb.get("games")):
            return None
        if kind == "consolation_bracket":
            return (p, tb, ref, _losers_bracket_of(s))
        if kind == "consolation":
            return (tb,)
        return (s, tb)
    return None


def report_parts(s: Season, seasons: dict | None = None,
                 playoffs: dict | None = None, manager: str | None = None) -> dict:
    """The report's content as data, so any surface can render it.

    Returns the headings, tiles, narrative, lead table and an ordered list of
    sections. Each section carries EITHER pre-built `html` (the manager tables)
    or a list of `charts` as `(chart_key, caption)`; the standalone file renders
    those keys to embedded PNGs, the dashboard tab points <img> at /chart/<key>.

    `portrait_style` is a `<style>` block backing every `.pface`/`.face` token in
    the section HTML (one deduped rule per unique image); both surfaces must emit
    it once for the portraits to show.
    """
    _reset_portrait_registry()
    scoped = bool(manager) and (s.standings["user_name"] == manager).any()
    if scoped:
        # Season position ranks, computed once and threaded through every
        # section, so a player row reads "Bijan Robinson RB #2" here the same
        # way it does on the Roster / Draft / Playoffs tabs. Best-effort.
        try:
            ranks = metrics.season_position_ranks(s)
        except Exception:
            ranks = {}
        # A manager report stays about THEM -- their game log, where their points
        # came from, their own playoff run, and their own career -- rather than
        # restating the whole-league charts. The one cross-manager view kept is
        # the ranking table (their rank, plus the best/worst team per category).
        sections = [
            ("Week by week", "Their season game by game, expand a week for its detail.",
             _game_log(s, manager, ranks),
             [("mgr_score_band", "Weekly score against the league's range"),
              ("mgr_optimal", "Started vs optimal, and the running cost of the bench"),
              ("mgr_margins", "Margin by week: blowouts vs coin flips")]),
            ("Where the points came from", "Started points by position for this "
             "roster, and how each ranks in the league.",
             _position_mix(s, manager, ranks), []),
            *_split_section(
                "Season standouts",
                "Who carried the team, and the best moves off the waiver wire "
                "and in trades.",
                _mgr_standouts(s, manager, ranks),
                "The season-long roster, best first."),
            *_split_section(
                "Draft class", "How their draft paid off: steals and reaches.",
                _mgr_draft(s, manager, ranks),
                "Every pick, in draft order."),
            ("Trades & the waiver wire", "Every deal they made and every player "
             "they picked up, expand one for what it returned.",
             _mgr_transactions(s, manager, ranks), []),
            ("Rivalries", "Their record against the rest of the league, expand one "
             "for every meeting.", _mgr_rivalry(s, manager, seasons), []),
            ("Splits & awards", "The season sliced a few ways.",
             _mgr_splits(s, manager), []),
            ("Their postseason", "", _mgr_postseason(s, manager, playoffs, ranks), []),
            ("Their career", "", _mgr_career(s, manager, seasons, playoffs), []),
        ]
        out = {
            "scoped": True, "eyebrow": "Manager report",
            "heading_text": str(manager), "subhead": f"{s.name} · {s.season}",
            "heading_html": (f"{html.escape(str(manager))}<br>"
                             f"<span class='subhead'>{html.escape(s.name)} · "
                             f"{s.season}</span>"),
            "title": f"{html.escape(str(manager))} · {s.season} Manager Report",
            # Flat (label, value, sub) headline tiles: a manager report is about
            # one person, so there is no opposed best/worst pair to merge -- the
            # cross-manager view here is the per-category rank table below.
            "tiles": _manager_tiles(s, manager),
            "tiles_kind": "flat",
            "narrative": _manager_narrative(s, manager, seasons),
            "table_title": "Where they rank",
            "table_blurb": ("How they place in each category: their rank, and the "
                            "league's best and worst."),
            "table_html": _neighborhood(s, manager) + _rank_table(s, manager),
        }
    else:
        sections = [
            ("The standings", "Where the season finished, and how deserved it was.", "",
             [("standings", "Final standings"),
              ("power_rank", "Composite power ranking"),
              ("allplay", "All-play: standings independent of schedule"),
              ("luck", "Luck: actual vs all-play expected wins")]),
            ("Lineup efficiency & scoring",
             "Who set the best lineups and who ran hot or cold.", "",
             [("efficiency", "Lineup efficiency"),
              ("consistency", "Weekly score distributions"),
              ("pf_pa", "Points for vs against")]),
            ("The weekly story", "How the table and the scoring moved week to week.", "",
             [("table_position", "Weekly table position"),
              ("team_points", "Weekly team points")]),
            ("Rosters & positions", "Where each team's points came from.", "",
             [("position_scoring", "Scoring by position"),
              ("roster_heatmap", "Roster construction")]),
            ("Managers & transactions",
             "Roster-building style, and what the moves returned.", "",
             [("manager_profile", "Manager tendencies"),
              ("trade_performance", "Traded-player value"),
              ("waiver_performance", "Waiver / FA value")]),
        ]
        # Postseason scoped to THIS season's bracket. The chart set
        # mirrors the webapp Playoffs tab: the bracket, the best playoff players
        # (spliced bars), then the consolation-bracket trio for the teams that
        # missed the championship bracket -- included only when this season
        # actually had a consolation bracket (a season where every team made the
        # championship bracket has none), so the report never carries a blank
        # panel. Every panel is still best-effort at render time on top of this.
        if playoffs and s.season in playoffs:
            po_charts = [("bracket", f"{s.season} playoff bracket"),
                         ("playoff_players_splice",
                          "Best playoff players, each bar split into the games "
                          "that built it")]
            _cb, _ = _consolation_of(s, playoffs[s.season])
            if _cb and (_cb.get("teams") or _cb.get("games")):
                po_charts += [
                    ("consolation_bracket",
                     "The teams that missed the championship bracket"),
                    ("consolation_players_splice",
                     "Best scorers in the consolation bracket"),
                    ("consolation_clutch",
                     "Consolation PPG against regular-season PPG")]
            sections.append(("The postseason",
                             "How this season's bracket actually played out.", "",
                             po_charts))
        out = {
            "scoped": False, "eyebrow": "Season report",
            "heading_text": s.name, "subhead": str(s.season),
            "heading_html": f"{html.escape(s.name)}<br>{s.season}",
            "title": f"{html.escape(s.name)} · {s.season} Season Report",
            "tiles": _insight_tiles(s),
            "tiles_kind": "insight",
            # No prose recap on the season report: the insight tiles above
            # already carry the same six facts summary_season() narrates, the
            # same call the webapp Overview made when it dropped its own
            # `summary | md` card. summary_season() itself is untouched (still
            # parity-mirrored, still used by the weekly report).
            "narrative": "",
            "table_title": "Team by team",
            "table_blurb": ("The whole season on one line each: record, points for "
                            "and against, all-play win %, power rank, lineup "
                            "efficiency, and waiver moves / trades."),
            "table_html": _team_table(s),
        }
    out["sections"] = [
        {"title": t, "blurb": b, "html": h, "charts": c,
         # Whether `html`'s own top-level element already draws a frame
         # (.drilltable / .draftboard, possibly after a leading <p> blurb) --
         # the dashboard tab needs this to pick a wrapper that doesn't double
         # box it. table.teams / .dt-facts draw no frame of their own and want
         # the wrapper's box, so this is False for those.
         "self_boxed": bool(re.search(
             r"(?:^|</p>)\s*<div class='(?:drilltable|draftboard)'", h))}
        for t, b, h, c in sections if h or c]
    # Built last: every section above has now registered its portraits.
    out["portrait_style"] = _portrait_style()
    return out


def _render_tiles(tiles: list, kind: str) -> str:
    """The headline tiles as HTML for the standalone file.

    `kind == "insight"` -- `{label, rows: [{tone, holder, value, detail}]}`
    merged good/bad tiles (the season report), rendered as the webapp's Overview
    tiles are: a label, then a ▲ good row and a ▼ bad row stacked inside.
    `kind == "flat"` -- `(label, value, sub)` triples (the manager report).
    """
    if kind == "insight":
        cells = []
        for t in tiles:
            rows = "".join(
                f"<div class='irow {r['tone']}'>"
                f"<span class='ir-mark'>{'&#9650;' if r['tone'] == 'good' else '&#9660;'}</span>"
                f"<span class='ir-who'>{html.escape(str(r['holder']))}</span>"
                f"<span class='ir-val'>{html.escape(str(r['value']))}</span>"
                + (f"<span class='ir-det'>{html.escape(str(r['detail']))}</span>"
                   if r.get("detail") else "")
                + "</div>"
                for r in t["rows"])
            cells.append(f"<div class='tile insight'><span class='k'>"
                         f"{html.escape(t['label'])}</span>"
                         f"<div class='irows'>{rows}</div></div>")
        return "".join(cells)
    return "".join(
        f"<div class='tile'><span class='k'>{html.escape(k)}</span>"
        f"<span class='v'>{html.escape(str(v))}</span>"
        f"<span class='s'>{html.escape(str(sub))}</span></div>"
        for k, v, sub in tiles)


def season_report(s: Season, path: str, seasons: dict | None = None,
                  playoffs: dict | None = None, manager: str | None = None) -> str:
    """Write a standalone HTML season report for `s`; returns the path.

    `seasons` (the league's whole chain) feeds the manager-scoped report's
    rivalry and career sections; `playoffs` (stored brackets) adds the
    postseason section for the report's season. `manager` scopes the report to
    one team (see `report_parts`). Charts are baked in as base64 PNGs so the
    file stands alone.
    """
    if not _has_scored_week(s):
        # A drafted-but-not-started season -- every section would be a zero.
        # Write a short standalone page instead of a report full of blanks.
        doc = _TEMPLATE.format(
            title=f"{s.name} {s.season} Season Report", eyebrow="Season report",
            heading=(f"{html.escape(s.name)}<br><span class='subhead'>"
                     f"{s.season}</span>"),
            generated=date.today().isoformat(),
            tiles="", narrative_block="",
            table_title="", table_blurb="",
            team_table=("<p class='empty'>No games have been scored yet this "
                        "season, so there is no season report to build. It "
                        "fills in once week 1 is complete.</p>"),
            sections="", css=_CSS, portrait_style="")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        return path
    parts = report_parts(s, seasons, playoffs, manager)
    tiles = _render_tiles(parts["tiles"], parts.get("tiles_kind", "flat"))

    rendered = []
    for sec in parts["sections"]:
        # A section may carry a table, charts, or both (the manager report's
        # week-by-week is a game log followed by its charts), so never treat
        # `html` as excluding `charts`.
        if sec["html"]:
            rendered.append(_html_section(sec["title"], sec["blurb"], sec["html"]))
        figs = []
        for key, desc in sec["charts"]:
            fn, kind = _CHART_FNS.get(key, (None, None))
            args = _chart_args(kind, s, seasons, playoffs, manager)
            if fn is None or args is None:
                continue
            figs.append(_fig(fn, *args, _desc=desc))
        # Heading already emitted above if this section also had a table.
        title = "" if sec["html"] else sec["title"]
        blurb = "" if sec["html"] else sec["blurb"]
        rendered.append(_section(title, blurb, *figs))

    body = "".join(sec for sec in rendered if sec)
    # The prose lead only rides above the table when there is one -- the season
    # report drops it (its insight tiles say the same), the manager report keeps
    # its manager-specific narrative.
    narrative_block = (
        '<div class="lead"><h2 style="border:0;padding:0;margin:14px 0 0">'
        f'What the numbers say</h2>{parts["narrative"]}</div>'
        if parts["narrative"] else "")
    doc = _TEMPLATE.format(
        title=parts["title"], eyebrow=parts["eyebrow"],
        heading=parts["heading_html"],
        generated=date.today().isoformat(),
        tiles=tiles, narrative_block=narrative_block,
        table_title=parts["table_title"], table_blurb=parts["table_blurb"],
        team_table=parts["table_html"],
        sections=body, css=_CSS,
        portrait_style=parts.get("portrait_style", ""))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#5b616e;--faint:#9aa0a6;
 --line:#e6e8eb;--accent:#2c7fb8;--gold:#e6b400;--radius:14px}
@media (prefers-color-scheme:dark){:root{--bg:#111316;--card:#1a1d21;--ink:#e9ebee;
 --muted:#a7adb8;--faint:#6b7280;--line:#2a2e35;--accent:#5aa9de;--gold:#f1c40f}}
:root[data-theme=dark]{--bg:#111316;--card:#1a1d21;--ink:#e9ebee;--muted:#a7adb8;
 --faint:#6b7280;--line:#2a2e35;--accent:#5aa9de;--gold:#f1c40f}
:root[data-theme=light]{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#5b616e;
 --faint:#9aa0a6;--line:#e6e8eb;--accent:#2c7fb8;--gold:#e6b400}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:clamp(20px,4vw,48px)}
header.top{display:flex;justify-content:space-between;align-items:flex-end;
 gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:18px}
header.top .eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:12px;
 color:var(--accent);font-weight:700}
header.top h1{margin:.1em 0 0;font-size:clamp(30px,5vw,46px);line-height:1.02;
 letter-spacing:-.02em;text-wrap:balance}
header.top h1 .subhead{font-size:.42em;font-weight:600;letter-spacing:0;
 color:var(--muted)}
header.top .gen{color:var(--faint);font-size:13px;text-align:right}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));
 gap:14px;margin:26px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 padding:16px 18px;display:flex;flex-direction:column;gap:2px}
.tile .k{text-transform:uppercase;letter-spacing:.06em;font-size:11px;
 color:var(--faint);font-weight:700}
.tile .v{font-size:30px;font-weight:750;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums;line-height:1.1}
.tile:first-child .v{color:var(--gold)}
.tile .s{font-size:12.5px;color:var(--muted)}
/* Merged good/bad insight tiles (the season report) -- a ▲ best row and a ▼
   worst row stacked under one label, mirroring the webapp Overview tab. */
.tile.insight{gap:6px}
.tile.insight .irows{display:flex;flex-direction:column;gap:8px;margin-top:2px}
.tile.insight .irow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;
 align-items:center;column-gap:8px}
.tile.insight .ir-mark{font-size:11px;line-height:1}
.tile.insight .irow.good .ir-mark{color:#2f9e44}
.tile.insight .irow.bad .ir-mark{color:#e03131}
.tile.insight .ir-who{min-width:0;font-size:13.5px;font-weight:650;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile.insight .ir-val{font-size:14.5px;font-weight:700;font-variant-numeric:tabular-nums}
.tile.insight .ir-det{grid-column:2 / -1;font-size:11px;color:var(--muted)}
.lead{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
 border-radius:var(--radius);padding:6px 22px;margin:24px 0}
.lead ul{margin:12px 0;padding-left:20px}.lead li{margin:5px 0}
.lead strong{color:var(--ink)}
h2{font-size:22px;letter-spacing:-.01em;margin:40px 0 2px;
 padding-top:22px;border-top:1px solid var(--line)}
.blurb{color:var(--muted);margin:.2em 0 14px;font-size:14.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:20px}
figure{margin:0;background:var(--card);border:1px solid var(--line);
 border-radius:var(--radius);padding:12px;overflow:hidden}
figure img{width:100%;height:auto;display:block;border-radius:8px}
figcaption{color:var(--faint);font-size:12px;margin-top:8px;padding:0 4px}
.teamsec{overflow-x:auto}
table.teams{width:100%;border-collapse:collapse;font-size:14px;
 background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 overflow:hidden}
table.teams th,table.teams td{padding:10px 12px;text-align:left;
 border-bottom:1px solid var(--line);white-space:nowrap}
table.teams th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
 color:var(--faint);font-weight:700;background:color-mix(in srgb,var(--ink) 4%,transparent)}
table.teams td.n,table.teams th.n{text-align:right;font-variant-numeric:tabular-nums}
table.teams td.rank{color:var(--faint);font-variant-numeric:tabular-nums}
table.teams td.name{font-weight:650}
table.teams td.res{font-weight:700}
table.teams td.res.w{color:#2f9e44}table.teams td.res.l{color:#e03131}
table.teams .q{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12.5px}
table.teams tr.gap td{text-align:center;color:var(--faint);padding:4px 12px}
/* green/red delta pills in a numeric cell, the Draft-finds convention. */
.res{font-weight:700;font-variant-numeric:tabular-nums}
.res.w{color:#2f9e44}.res.l{color:#e03131}
/* Draft class laid out like the webapp Draft-finds table. */
table.teams.draftfinds td.name .q.posrank,table.teams.draftfinds td.name .pos{
 margin-left:6px}
.spark-line{display:inline-block;width:56px;height:16px;vertical-align:middle}
.spark-line line{vector-effect:non-scaling-stroke}
.spark-line .spark-avg{stroke:var(--faint);stroke-width:1;stroke-dasharray:2 2}
.spark-line line.up{stroke:#2f9e44;stroke-width:1.5}
.spark-line line.down{stroke:#e03131;stroke-width:1.5}
/* Bare .q -- the site's small muted-text convention, used outside table.teams
   (the .plr-pts line below, the deal-meta verdict). */
.q{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12.5px}
.tag{display:inline-block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;
 color:var(--muted);white-space:nowrap;border:1px solid var(--line);border-radius:20px;
 padding:1px 8px}
/* Trade "deal" cards, ported from the webapp Transactions tab -- one card per
   deal, one .side per team, one .plr row per player they received. */
.deals{display:grid;gap:14px}
.deal-group{display:flex;flex-direction:column;gap:8px}
.deal-meta{display:flex;align-items:baseline;gap:10px;padding:0 2px 7px;
 border-bottom:1px solid var(--line)}
.deal-meta .wk{font-size:11px;font-weight:700;letter-spacing:.06em;
 text-transform:uppercase;color:var(--faint)}
.deal-meta .verdict{margin-left:auto;font-size:12.5px;color:var(--muted)}
.deal-meta .verdict b{color:var(--ink)}
.deal-meta .verdict.even{font-style:italic}
.deal{position:relative;border:1px solid var(--line);border-radius:12px;
 overflow:hidden;background:var(--card)}
.deal .deal-tag{position:absolute;top:10px;right:12px;z-index:1}
.deal .sides{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
.deal .side{padding:12px 14px;min-width:0;border-top:1px solid transparent}
.deal .side+.side{box-shadow:inset 1px 0 0 var(--line)}
.deal .side.up{background:color-mix(in srgb,#2f9e44 8%,transparent)}
.deal .side.down{background:color-mix(in srgb,#e03131 6%,transparent)}
.deal .who{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
 font-weight:650;font-size:13.5px;padding-bottom:8px;margin-bottom:8px;
 border-bottom:1px solid color-mix(in srgb,var(--ink) 16%,transparent)}
.deal .got{margin-top:6px;font-size:13px;line-height:1.5}
.deal .plr{margin-top:8px}
.deal .plr:first-child{margin-top:0}
.deal .plr-name{display:flex;align-items:center;gap:6px}
.deal .plr-from{margin-top:2px;padding-left:28px}
.deal .plr-pts{margin-top:2px;padding-left:28px}
@media(max-width:620px){.deal .side+.side{box-shadow:none;border-top-color:var(--line)}
 .deal .sides{grid-template-columns:1fr}}
/* A table whose rows each expand (native <details>, no script) to show detail. */
.drilltable{border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;
 background:var(--card)}
.dt-head,.dt-row>summary{display:grid;grid-template-columns:var(--cols);gap:8px;
 padding:9px 30px 9px 14px;align-items:center}
.dt-head{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);
 font-weight:700;background:color-mix(in srgb,var(--ink) 4%,transparent)}
.dt-row{border-top:1px solid var(--line)}
.dt-row>summary{position:relative;cursor:pointer;list-style:none;font-size:13.5px}
.dt-row>summary::-webkit-details-marker{display:none}
.dt-row>summary::after{content:'\\25B8';position:absolute;right:13px;top:50%;
 transform:translateY(-50%);color:var(--faint);font-size:10px}
.dt-row[open]>summary::after{content:'\\25BE'}
.dt-row[open]>summary{background:color-mix(in srgb,var(--accent) 7%,transparent)}
.dt-num{text-align:right;font-variant-numeric:tabular-nums}
/* A .grp-end column closes a conceptual cluster in a _drill_table's own grid
   row (same convention as _mini_table's .grp-end, just via margin since a
   CSS grid spaces items with a single shared `gap`, not per-item padding). */
.dt-head .grp-end,.dt-row>summary .grp-end{margin-right:16px}
.dt-detail{padding:15px 16px 17px;font-size:12.5px;color:var(--muted);
 border-top:1px solid var(--line);line-height:1.6;overflow-x:auto;
 background:color-mix(in srgb,var(--ink) 3.5%,transparent)}
.dt-detail strong{color:var(--ink)}
.dt-row .res.w{color:#2f9e44;font-weight:700}.dt-row .res.l{color:#e03131;font-weight:700}
/* Drill bodies are labelled fields / mini-tables, never a run-on sentence. */
.dt-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(184px,1fr));
 gap:16px 28px}
.fact{display:flex;flex-direction:column;gap:3px;min-width:0}
.fl{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);
 font-weight:700;line-height:1.3}
.fv{font-size:13.5px;color:var(--ink);line-height:1.5;white-space:normal;
 overflow-wrap:anywhere}
.fv .pos{color:var(--muted);font-size:11px;font-weight:600;margin-left:4px}
.fv .pts{font-variant-numeric:tabular-nums;font-weight:700}
.fv .q{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
/* A player fact: identity line, then figure + note beneath it. */
.fv .fpl{display:flex;align-items:center;gap:2px;flex-wrap:wrap;font-weight:650}
.fv .fpl .posrank{margin-left:6px}
.fv .fnum{display:block;margin-top:3px;color:var(--muted)}
.fv .fnum .pts{color:var(--ink);margin-right:6px}
.fv .fnote{font-size:12px}
table.dt-games{border-collapse:collapse;font-size:12.5px;width:auto;margin-top:2px}
.dt-detail .dt-facts+table.dt-games,.dt-detail .dt-facts+.dt-tables{margin-top:16px}
/* Side-by-side mini-tables in a drill body (Started | Bench, Got | Gave):
   two even columns with a hairline gutter, stacking only when truly narrow. */
.dt-tables{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
 gap:16px 26px;align-items:start}
.dt-tables>.dt-block+.dt-block{border-left:1px solid var(--line);padding-left:26px}
@media(max-width:640px){.dt-tables{grid-template-columns:1fr}
 .dt-tables>.dt-block+.dt-block{border-left:0;padding-left:0;
  border-top:1px solid var(--line);padding-top:14px}}
.dt-block{min-width:0;overflow-x:auto}
/* table.dt-games is width:auto by default, right for a table sitting bare at
   its own natural size. Wrapped in .dt-tables (a grid cell) or a lone
   .dt-block (used to keep a mini-table out of a stretched container without
   giving it a caption), the WRAPPER stretches but a width:auto table inside
   it does not, leaving dead space beside a narrow table instead of the table
   filling the column -- fill it explicitly in both wrapped contexts. */
.dt-tables>table.dt-games,.dt-tables>.dt-block>table.dt-games,
.dt-block>table.dt-games{width:100%}
.dt-sub{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);
 font-weight:700;margin-bottom:6px}
table.dt-games th{font-size:10px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--faint);font-weight:700;text-align:left;padding:0 26px 8px 0;border:0}
table.dt-games td{padding:7px 26px 7px 0;white-space:nowrap;border:0;color:var(--ink)}
table.dt-games tbody tr:not(:last-child) td{border-bottom:1px solid var(--line)}
table.dt-games th:last-child,table.dt-games td:last-child{padding-right:0}
table.dt-games td.n,table.dt-games th.n{text-align:right;font-variant-numeric:tabular-nums}
/* _mini_table's 4-9 column tables (Season standouts, waiver drill, position
   mix) -- the base 26px right-padding is sized for a 2-3 column lineup
   table; that many columns at 26px each reads as loose gaps once the table
   is stretched to fill its wrapper (see the width:100% rule above). Matches
   table.dt-games th/td's own (0,1,2) specificity via the extra .dt-games
   class rather than relying on source-order tie-break.
   table-layout:fixed is the load-bearing part: table-layout:auto sizes
   every column purely from its own content, so a table with no single wide
   (text) column -- e.g. Wk/Role/Pts/Running/Wk rank/Share, all short --
   spreads its columns evenly across width:100% regardless of any padding
   difference, which is what actually read as "auto spaced" (a table WITH
   a dominant wide column, like Player, happened to look grouped by
   accident). Fixed layout hands width control to the <colgroup> instead
   (see _colgroup/`widths`), so grouping is deterministic either way. Now
   that group SEPARATION is a real spacer column (.gap-col, see below), the
   padding between columns WITHIN a group only needs to be a small
   breathing-room gap, not a second, weaker attempt at the same job. */
table.dt-games.dt-games-compact{table-layout:fixed}
table.dt-games.dt-games-compact th{padding-right:10px;overflow:hidden;text-overflow:ellipsis}
table.dt-games.dt-games-compact td{padding-right:10px;overflow:hidden;text-overflow:ellipsis}
/* Column grouping is a REAL empty spacer <col>/<td class="gap-col"> between
   groups (_spaced_cols), not cell padding -- under table-layout:fixed a
   column's width is fixed by its own <col>, and a cell's padding cannot
   push a SIBLING column's boundary rightward at all (confirmed: bumping
   the trailing column's padding-right from 24px to 3em produced no visible
   change, since the columns after it were already exactly where their own
   <col> widths put them). The spacer <col> carries its own small fixed ch
   width (_GAP_CH) so it joins the proportional pool table-layout:fixed
   distributes leftover width across, staying a modest gap; leaving it
   width-less made it swallow the whole table's leftover space, squeezing
   every real column and clipping headers. Don't zero out `border`
   wholesale -- that also killed border-bottom (the row divider, tbody
   tr:not(:last-child) td), breaking the horizontal line at every spacer. */
table.dt-games.dt-games-compact td.gap-col,
table.dt-games.dt-games-compact th.gap-col{padding:0;border-left:0;
 border-right:0;border-top:0}
/* Stacked blocks inside one section need real separation. */
.teamsec table.teams+table.teams,.teamsec table.teams+.drilltable,
.teamsec table.teams+.dt-facts,.teamsec .drilltable+table.teams,
.teamsec .drilltable+.dt-facts,.teamsec .dt-facts+table.teams,
.teamsec .dt-facts+.drilltable{margin-top:26px}
.teamsec p.blurb{margin:2px 2px 14px}
.teamsec table.teams+p.blurb,.teamsec .drilltable+p.blurb{margin-top:20px}
/* A section continued under the heading above it (empty <h2>) still gets air
   between it and the block before. */
section+section.contd{margin-top:26px}
/* Rank badges: top third good, bottom third bad. */
.rankpill{display:inline-block;padding:1px 9px;border-radius:20px;font-size:11.5px;
 font-weight:700;font-variant-numeric:tabular-nums;border:1px solid transparent}
.rankpill .of{font-weight:500;opacity:.65}
.rankpill.good{color:#2f9e44;background:rgba(47,158,68,.14);border-color:rgba(47,158,68,.35)}
.rankpill.mid{color:var(--muted);background:color-mix(in srgb,var(--ink) 7%,transparent);
 border-color:var(--line)}
.rankpill.bad{color:#e03131;background:rgba(224,49,49,.13);border-color:rgba(224,49,49,.32)}
table.teams td.val{font-weight:700;color:var(--ink);font-size:14.5px}
.peer{color:var(--muted)}
.peer.is-me{color:var(--ink);font-weight:700;box-shadow:inset 0 -2px 0 var(--accent)}
table.teams tbody tr:last-child td{border-bottom:0}
/* Gold-tint the top row only where the table is ranked (leader/champion) -- not
   on category/game-log tables, where the first row isn't special. */
table.teams.lead tbody tr:first-child td{background:color-mix(in srgb,var(--gold) 10%,transparent)}
/* The scoped manager's row wins over the champion tint (declared later). */
table.teams tbody tr.me td{background:color-mix(in srgb,var(--accent) 14%,transparent);
 font-weight:650;box-shadow:inset 3px 0 0 var(--accent)}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
 color:var(--faint);font-size:12.5px;display:flex;justify-content:space-between;
 gap:12px;flex-wrap:wrap}
@media(max-width:520px){.grid{grid-template-columns:1fr}}
/* Player portraits + manager avatars, matching the webapp's inline identity
   tokens. Each is a <span> whose background-image is one deduped data URI rule
   in the report's <style> block (see report._portrait_style), so the same face
   in a dozen tables is embedded once. A missing one isn't emitted at all and
   the name stands alone. */
.pface,.face{display:inline-block;width:20px;height:20px;border-radius:50%;
 vertical-align:-5px;margin-right:6px;background-color:color-mix(in srgb,var(--ink) 8%,transparent);
 background-size:cover;background-position:center;background-repeat:no-repeat}
.fv .pface,.fv .face{width:22px;height:22px;vertical-align:-6px}
/* The POS #rank badge, e.g. "WR #4" -- a season position finish. */
.q.posrank{margin-left:6px;white-space:nowrap}
/* A lineup row the best legal lineup would have swapped (started -> bench or
   bench -> started), the same gold cue the webapp's .bench-impact uses. */
tr.bench-impact>td{background:color-mix(in srgb,var(--gold) 15%,transparent)}
"""

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style>{portrait_style}</head>
<body><div class="wrap">
<header class="top">
  <div><div class="eyebrow">{eyebrow}</div><h1>{heading}</h1></div>
  <div class="gen">Generated {generated}<br>Data: public Sleeper API</div>
</header>
<div class="tiles">{tiles}</div>
{narrative_block}
<section><h2>{table_title}</h2>
<p class="blurb">{table_blurb}</p>
<div class="teamsec">{team_table}</div></section>
{sections}
<footer><span>Champions come from the stored playoff brackets, not Sleeper&rsquo;s
winners_bracket.</span><span>sleepermetrics</span></footer>
</div></body></html>"""
