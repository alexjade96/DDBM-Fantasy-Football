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

from . import metrics, plots, summaries  # noqa: E402
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


def _tiles(s: Season) -> list[tuple[str, str, str]]:
    """The headline numbers: (label, value, sub)."""
    st = s.standings
    lead = st.sort_values("final_position").iloc[0]
    champ = st[st["champion"]]
    champ_name = champ["user_name"].iloc[0] if len(champ) else lead["user_name"]
    tw = s.team_wk
    top = tw.loc[tw["points"].idxmax()]
    ap = metrics.allplay(s).iloc[0]
    lk = metrics.luck(s).iloc[0]
    eff = metrics.efficiency(s).iloc[0]
    return [
        ("Champion", champ_name, f"{lead['wins']:.0f}-{lead['losses']:.0f} at the top"),
        ("Most points", f"{st['points'].max():.0f}", st.sort_values('points').iloc[-1]["user_name"]),
        ("Highest week", f"{top['points']:.1f}", f"{top['user_name']} · wk {int(top['week'])}"),
        ("Best all-play", f"{ap['allplay_pct'] * 100:.0f}%", f"{ap['user_name']} · schedule-proof"),
        ("Luckiest", f"{lk['luck']:+.1f}", f"{lk['user_name']} · wins vs merit"),
        ("Sharpest lineup", f"{eff['eff']:.0f}%", f"{eff['user_name']} · of optimal"),
    ]


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _manager_tiles(s: Season, manager: str) -> list[tuple[str, str, str]]:
    """The headline numbers scoped to one manager."""
    st = s.standings
    row = st[st["user_name"] == manager]
    if row.empty:
        return _tiles(s)
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
        f"On all-play — every team, every week — they ranked #{int(apr['allplay_rank'])}, "
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
    """A section whose body is a raw HTML table (not a grid of figures)."""
    if not inner:
        return ""
    sub = f"<p class='blurb'>{html.escape(blurb)}</p>" if blurb else ""
    return (f"<section><h2>{html.escape(title)}</h2>{sub}"
            f"<div class='teamsec'>{inner}</div></section>")


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


def _mgr_postseason(s: Season, manager: str, playoffs: dict | None) -> str:
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
            rows.append((
                [(rnd, False), ("<span class='q'>First-round bye</span>", False),
                 ("—", True), ("—", True), ("<span class='res'>—</span>", True)],
                ""))
            continue
        cls = {"W": "w", "L": "l"}.get(str(g["result"]), "")
        cells = [
            (rnd, False), (html.escape(str(g["opponent"])), False),
            (f"{g['points']:.1f}", True), (f"{g['opp_points']:.1f}", True),
            (f"<span class='res {cls}'>{g['result']}</span>", True)]
        rows.append((cells, _playoff_round_detail(s, manager, p, g)))
    table = _drill_table(
        [("Round", False), ("Opponent", False), ("PF", True), ("PA", True),
         ("Result", True)],
        "minmax(150px,1.4fr) minmax(120px,1fr) 80px 80px 80px", rows)
    return (f"<p class='blurb'>{html.escape(outcome)}</p>" + table
            + _mgr_playoff_roster(s, manager, p))


def _playoff_round_detail(s: Season, manager: str, p, g) -> str:
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
    facts.append(("Top scorer", _player_fact(top)))
    if len(mine_pl) > 1:
        facts.append(("Quietest starter", _player_fact(mine_pl.iloc[-1])))
    if not opp_pl.empty:
        facts.append((f"{g['opponent']}'s best", _player_fact(opp_pl.iloc[0])))
    if pd.notna(g.get("margin")):
        m = float(g["margin"])
        shape = ("a coin flip" if abs(m) <= 10 else
                 "comfortable" if abs(m) <= 40 else "a rout")
        facts.append(("Margin", f"<span class='pts'>{m:+.1f}</span> "
                                f"<span class='q'>{shape}</span>"))
    if pd.notna(g.get("weeks")):
        facts.append(("Week(s)", html.escape(str(g["weeks"]))))
    swap = _bench_regret(s, manager, g, mine_pl)
    if swap:
        facts.append(swap)

    def lineup(df):
        return _mini_table(
            [("Slot", False), ("Player", False), ("Pts", True)],
            [[(html.escape(str(r["slot"])), False),
              (f"<strong>{html.escape(str(r['player_name']))}</strong>", False),
              (f"{float(r['points']):.1f}", True)] for _, r in df.iterrows()])

    tables = ("<div class='dt-tables'>"
              + _labeled(f"{manager} · {g['points']:.1f} pts", lineup(mine_lu))
              + _labeled(f"{g['opponent']} · {g['opp_points']:.1f} pts",
                         lineup(opp_lu))
              + "</div>")
    return _facts(facts) + tables


def _mgr_playoff_roster(s: Season, manager: str, p) -> str:
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
                  _player_fact(best, str(rmap.get(best["round_id"], "")))))
    if len(mine_pl) > 1:
        facts.append(("Quietest starter",
                      _player_fact(worst, str(rmap.get(worst["round_id"], "")))))

    # Per-round bench regret now lives in that round's own drill-down, so this
    # block stays the run-level summary.
    return _facts(facts)


def _bench_regret(s: Season, manager: str, g, started_pl):
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
    return ("Bench call",
            f"<strong>{html.escape(str(b['player_name']))}</strong> "
            f"<span class='pts'>{float(b['points']):.1f}</span> "
            f"<span class='q'>benched for "
            f"{html.escape(str(weak['player_name']))} "
            f"{float(weak['points']):.1f} · {flip}</span>")


def _mgr_career(s: Season, manager: str, seasons: dict | None) -> str:
    """One manager's own career: a line per season, plus their all-time standing."""
    if not seasons or len(seasons) < 2:
        return ""
    uid = s.standings.loc[s.standings["user_name"] == manager, "user_id"]
    if uid.empty:
        return ""
    uid = uid.iloc[0]
    rows = []
    for yr in sorted(seasons):
        r = seasons[yr].standings
        r = r[r["user_id"] == uid]
        if r.empty:
            continue
        r = r.iloc[0]
        star = " ★" if bool(r["champion"]) else ""
        rows.append(
            f"<tr><td class='rank'>{yr}</td>"
            f"<td class='n'>#{int(r['final_position'])}{star}</td>"
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
        "<th class='n'>Finish</th><th>Record</th><th class='n'>PF</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _drill_table(cols: list, template: str, rows: list) -> str:
    """A table whose rows each expand to a detail panel (native <details>).

    `cols`: list of (label, is_num). `template`: CSS grid-template-columns.
    `rows`: list of (cells, detail) where `cells` is a list of (html, is_num) and
    `detail` is the HTML shown when that row is expanded ("" = not expandable).
    """
    if not rows:
        return ""
    head = "".join(f"<span class='{'dt-num' if num else ''}'>{html.escape(c)}</span>"
                   for c, num in cols)
    body = []
    for cells, detail in rows:
        sm = "".join(f"<span class='{'dt-num' if num else ''}'>{c}</span>"
                     for c, num in cells)
        det = f"<div class='dt-detail'>{detail}</div>" if detail else ""
        body.append(f"<details class='dt-row'><summary>{sm}</summary>{det}</details>")
    return (f"<div class='drilltable' style='--cols:{template}'>"
            f"<div class='dt-head'>{head}</div>" + "".join(body) + "</div>")


def _facts(pairs: list) -> str:
    """A drill-down body as labelled fields, not a run-on sentence."""
    if not pairs:
        return ""
    cells = "".join(
        f"<div class='fact'><span class='fl'>{html.escape(label)}</span>"
        f"<span class='fv'>{value}</span></div>" for label, value in pairs)
    return f"<div class='dt-facts'>{cells}</div>"


def _mini_table(cols: list, rows: list) -> str:
    """A compact table for inside a drill-down body.

    `cols` is [(label, is_num)], `rows` is [[(html, is_num), …]].
    """
    if not rows:
        return ""
    head = "".join(f"<th class='{'n' if num else ''}'>{html.escape(c)}</th>"
                   for c, num in cols)
    body = "".join(
        "<tr>" + "".join(f"<td class='{'n' if num else ''}'>{v}</td>" for v, num in r)
        + "</tr>" for r in rows)
    return (f"<table class='dt-games'><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>")


def _labeled(label: str, inner: str) -> str:
    """A small captioned block, for side-by-side tables inside a drill body."""
    if not inner:
        return ""
    return (f"<div class='dt-block'><div class='dt-sub'>{html.escape(label)}</div>"
            f"{inner}</div>")


def _fact_player(name, pos, pts: str, note: str = "") -> str:
    """A player as name + position + a figure, for a fact field."""
    tail = f" <span class='q'>{note}</span>" if note else ""
    return (f"<strong>{html.escape(str(name))}</strong> "
            f"<span class='pos'>{html.escape(str(pos))}</span> "
            f"<span class='pts'>{pts}</span>{tail}")


def _player_fact(r, note: str = "") -> str:
    """A player row (player_name/position/points) as a fact field."""
    return _fact_player(r["player_name"], r["position"],
                        f"{float(r['points']):.1f}", note)


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


def _pts_on_roster(s: Season) -> dict:
    """{(player_id, roster_id): points scored while on that roster} from pl_wk.

    pl_wk records roster membership week by week, so summing it per (player,
    roster) already answers "what did they score for that team" -- no need to
    reconstruct transaction stints, and a player traded mid-season contributes
    to each roster separately.
    """
    pl = s.pl_wk
    if not {"player_id", "roster_id", "points"}.issubset(getattr(pl, "columns", [])):
        return {}
    g = pl.groupby([pl["player_id"].astype(str), pl["roster_id"]])["points"].sum()
    return {k: float(v) for k, v in g.items()}


def _mgr_transactions(s: Season, manager: str) -> str:
    """One manager's season of dealing: trades, then the waiver wire.

    Trades are grouped by `transaction_id` so a deal reads as a deal -- what
    they got against what they gave, and what each side went on to score -- and
    pickups are listed by what they actually returned.
    """
    rid = _mgr_roster_id(s, manager)
    tx = getattr(s, "transactions", None)
    need = {"week", "transaction_id", "type", "transaction", "player_id",
            "roster_id", "player_name", "position"}
    if rid is None or tx is None or not need.issubset(getattr(tx, "columns", [])):
        return ""
    t = tx.copy()
    if "status" in t.columns:
        t = t[t["status"] != "failed"]
    t["player_id"] = t["player_id"].astype(str)
    pts = _pts_on_roster(s)
    rname = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))

    def plist(rows, holder_of):
        """A mini-table of players with the points they scored for `holder_of`."""
        return _mini_table(
            [("Player", False), ("Pos", False), ("Pts", True)],
            [[(f"<strong>{html.escape(str(r.player_name))}</strong>", False),
              (html.escape(str(r.position)), False),
              (f"{pts.get((r.player_id, holder_of(r)), 0.0):.1f}", True)]
             for r in rows.itertuples()])

    # --- trades, one row per deal ---
    trade_rows = []
    tr = t[t["type"] == "trade"]
    mine_ids = set(tr.loc[tr["roster_id"] == rid, "transaction_id"])
    for tid in sorted(mine_ids, key=lambda i: (tr.loc[tr["transaction_id"] == i,
                                                      "week"].min(), str(i))):
        ev = tr[tr["transaction_id"] == tid]
        got = ev[(ev["roster_id"] == rid) & (ev["transaction"] == "add")]
        gave = ev[(ev["roster_id"] == rid) & (ev["transaction"] == "drop")]
        # Where each player I gave up ended up, so their points count against
        # the right roster (a three-way trade has more than one counterparty).
        dest = dict(zip(ev[(ev["transaction"] == "add")
                           & (ev["roster_id"] != rid)]["player_id"],
                        ev[(ev["transaction"] == "add")
                           & (ev["roster_id"] != rid)]["roster_id"]))
        others = sorted({rname.get(r, str(r)) for r in ev.loc[
            ev["roster_id"] != rid, "roster_id"]})
        wk = int(ev["week"].min())
        mine_ret = sum(pts.get((p, rid), 0.0) for p in got["player_id"])
        their_ret = sum(pts.get((p, dest.get(p)), 0.0) for p in gave["player_id"])
        net = mine_ret - their_ret
        cls = "w" if net > 0 else "l" if net < 0 else ""
        cells = [
            (str(wk), True),
            (html.escape(", ".join(others)) or "—", False),
            (html.escape(", ".join(got["player_name"].astype(str))) or "—", False),
            (html.escape(", ".join(gave["player_name"].astype(str))) or "—", False),
            (f"<span class='res {cls}'>{net:+.0f}</span>", True)]
        detail = _facts([
            ("Got back", f"<span class='pts'>{mine_ret:.1f}</span> "
                         "<span class='q'>pts while on their roster</span>"),
            ("Gave up", f"<span class='pts'>{their_ret:.1f}</span> "
                        "<span class='q'>pts for the other side after the deal</span>"),
            ("Net", f"<span class='pts'>{net:+.1f}</span>"),
        ]) + ("<div class='dt-tables'>"
              + _labeled("Got", plist(got, lambda r: rid))
              + _labeled("Gave", plist(gave, lambda r: dest.get(r.player_id)))
              + "</div>")
        trade_rows.append((cells, detail))

    # --- waiver / free-agent pickups, best return first ---
    pl = s.pl_wk
    have_pl = {"roster_id", "week", "player_id", "points"}.issubset(
        getattr(pl, "columns", []))
    adds = t[(t["type"].isin(["waiver", "free_agent"]))
             & (t["transaction"] == "add") & (t["roster_id"] == rid)]
    drops = t[(t["transaction"] == "drop") & (t["roster_id"] == rid)]
    # Last drop wins: a player cut, re-added and cut again reads by his exit.
    drop_wk = drops.groupby("player_id")["week"].max().to_dict()
    final = (set(pl.loc[(pl["roster_id"] == rid) & (pl["week"] == s.last_week),
                        "player_id"].astype(str))
             if have_pl and "week" in pl.columns else set())

    def still_on(pid):
        """On the roster in the final scored week (ground truth for 'dropped')."""
        return pid in final
    # One row per player, not per transaction: a player picked up, dropped and
    # picked up again is one story. Points are already a per-(player, roster)
    # total, so separate rows would repeat the same figure and read as two hits.
    picks = []
    for pid, g in adds.groupby("player_id", sort=False):
        first = g.iloc[0]
        weeks = sorted(int(w) for w in g["week"])
        kinds = sorted({("waiver" if k == "waiver" else "FA") for k in g["type"]})
        picks.append((pts.get((pid, rid), 0.0), pid, first, weeks, kinds))
    picks.sort(key=lambda x: -x[0])
    shown = picks[:15]
    waiver_rows = []
    for total, pid, r, weeks, kinds in shown:
        again = (f" <span class='q'>&times;{len(weeks)}</span>"
                 if len(weeks) > 1 else "")
        cells = [(str(weeks[0]), True),
                 (f"<strong>{html.escape(str(r['player_name']))}</strong>{again}",
                  False),
                 (html.escape(str(r["position"])), False),
                 (f"<span class='q'>{'/'.join(kinds)}</span>", False),
                 (f"{total:.0f}", True)]
        detail = ""
        if have_pl:
            wks = pl[(pl["roster_id"] == rid)
                     & (pl["player_id"].astype(str) == pid)]
            if not wks.empty:
                facts = []
                if len(weeks) > 1:
                    facts.append(("Picked up",
                                  f"<span class='pts'>{len(weeks)}&times;</span> "
                                  f"<span class='q'>weeks "
                                  f"{', '.join(str(w) for w in weeks)}</span>"))
                facts += [("Weeks rostered",
                           f"<span class='pts'>{wks['week'].nunique()}</span>"),
                          ("Avg per week",
                           f"<span class='pts'>{wks['points'].mean():.1f}</span>")]
                best = wks.loc[wks["points"].idxmax()]
                facts.append(("Best week",
                              f"<span class='pts'>{best['points']:.1f}</span> "
                              f"<span class='q'>wk {int(best['week'])}</span>"))
                if "is_starter" in wks.columns:
                    st = int(wks["is_starter"].sum())
                    facts.append(("Starts", f"<span class='pts'>{st}</span> "
                                            f"<span class='q'>of "
                                            f"{wks['week'].nunique()}</span>"))
                # Whether they actually left is roster membership in the final
                # scored week, not transaction order: a cut followed by a re-add
                # is churn, and an add and a drop in the SAME week can't be
                # sequenced from week numbers at all.
                if pid in drop_wk and not still_on(pid):
                    facts.append(("Dropped", f"<span class='q'>week "
                                             f"{int(drop_wk[pid])}</span>"))
                detail = _facts(facts) + _mini_table(
                    [("Wk", True), ("Pts", True), ("", False)],
                    [[(f"{int(x['week'])}", True),
                      (f"{float(x['points']):.1f}", True),
                      ("<span class='q'>started</span>"
                       if x.get("is_starter") else "", False)]
                     for _, x in wks.sort_values("week").iterrows()])
        waiver_rows.append((cells, detail))

    out = []
    if trade_rows:
        out.append("<p class='blurb'>Trades — net is what the players they got "
                   "scored for them, minus what the players they gave up scored "
                   "for the other side.</p>")
        out.append(_drill_table(
            [("Wk", True), ("With", False), ("Got", False), ("Gave", False),
             ("Net", True)],
            "50px minmax(110px,1fr) minmax(140px,1.5fr) minmax(140px,1.5fr) 80px",
            trade_rows))
    if waiver_rows:
        more = (f" Showing the top 15 of {len(picks)}." if len(picks) > 15 else "")
        out.append(f"<p class='blurb'>Waiver &amp; free-agent pickups, by what "
                   f"they returned while rostered.{more}</p>")
        out.append(_drill_table(
            [("Wk", True), ("Player", False), ("Pos", False), ("Via", False),
             ("Pts", True)],
            "50px minmax(150px,1.6fr) 60px 70px 80px", waiver_rows))
    return "".join(out)


def _mgr_standouts(s: Season, manager: str) -> str:
    """Who carried the team all season, and the best moves off waivers / trades."""
    rid = _mgr_roster_id(s, manager)
    pl = s.pl_wk
    facts, table = [], ""
    if rid is not None and {"roster_id", "is_starter", "player_name",
                            "position", "points"}.issubset(pl.columns):
        d = pl[(pl["roster_id"] == rid) & pl["is_starter"]]
        if not d.empty:
            g = (d.groupby(["player_name", "position"], as_index=False)["points"].sum()
                 .sort_values("points", ascending=False))
            top = g.iloc[0]
            facts.append(("Season MVP", _fact_player(
                top["player_name"], top["position"], f"{top['points']:.0f} pts")))
            # Each leader drills into how those points were actually accumulated.
            drows = []
            for r in g.head(12).itertuples():
                starts = d[d["player_name"] == r.player_name]
                cells = [(f"<strong>{html.escape(str(r.player_name))}</strong>", False),
                         (html.escape(str(r.position)), False),
                         (f"{r.points:.0f}", True)]
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
                    wk_tbl = _mini_table(
                        [("Wk", True), ("Pts", True)],
                        [[(f"{int(x['week'])}", True), (f"{float(x['points']):.1f}", True)]
                         for _, x in starts.sort_values("week").iterrows()])
                    detail = _facts(dfacts) + wk_tbl
                drows.append((cells, detail))
            table = _drill_table(
                [("Player", False), ("Pos", False), ("Started pts", True)],
                "1.6fr 60px 110px", drows)
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
                "while rostered")))
    if not facts:
        return ""
    return _facts(facts) + table


def _mgr_draft(s: Season, manager: str) -> str:
    """One manager's draft class, graded by what each pick returned."""
    from . import draft as _draft
    try:
        db = _draft.draft_board(s)
    except Exception:
        return ""
    if db.empty or "user_name" not in db.columns:
        return ""
    mine = db[db["user_name"] == manager].sort_values("pick_no")
    if mine.empty:
        return ""
    best = mine.loc[mine["steal"].idxmax()]
    worst = mine.loc[mine["steal"].idxmin()]
    summ = _facts([
        ("Best pick", _fact_player(
            best["player_name"], best["position"], f"{best['points']:.0f} pts",
            f"R{int(best['round'])} · #{int(best['pick_no'])} overall")),
        ("Biggest reach", _fact_player(
            worst["player_name"], worst["position"], f"{worst['points']:.0f} pts",
            f"R{int(worst['round'])} · #{int(worst['pick_no'])} overall")),
    ])
    rows = "".join(
        f"<tr><td class='rank'>{int(r.round)}.{int(r.draft_slot)}</td>"
        f"<td class='name'>{html.escape(str(r.player_name))}</td>"
        f"<td>{html.escape(str(r.position))}</td>"
        f"<td class='n'>#{int(r.pick_no)}</td><td class='n'>{r.points:.0f}</td></tr>"
        for r in mine.itertuples())
    table = ("<table class='teams'><thead><tr><th>Rd.Slot</th><th>Player</th>"
             "<th>Pos</th><th class='n'>Pick</th><th class='n'>Pts</th>"
             "</tr></thead><tbody>" + rows + "</tbody></table>")
    return summ + table


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
    parts = []
    strong = h[h["games"] >= 2]
    if len(strong):
        own = strong.loc[strong["win_pct"].idxmax()]
        nem = strong.loc[strong["win_pct"].idxmin()]
        if own["opp_name"] != nem["opp_name"]:
            parts.append(_facts([
                ("Owns", f"<strong>{html.escape(str(own['opp_name']))}</strong> "
                         f"<span class='pts'>{int(own['wins'])}-{int(own['losses'])}"
                         f"</span> <span class='q'>{own['win_pct']:.0f}%</span>"),
                ("Haunted by", f"<strong>{html.escape(str(nem['opp_name']))}</strong> "
                               f"<span class='pts'>{int(nem['wins'])}-"
                               f"{int(nem['losses'])}</span> "
                               f"<span class='q'>{nem['win_pct']:.0f}%</span>"),
            ]))
    rows = []
    for r in h.sort_values("win_pct", ascending=False).itertuples():
        rec = f"{int(r.wins)}-{int(r.losses)}" + (f"-{int(r.ties)}" if r.ties else "")
        cells = [(html.escape(str(r.opp_name)), False), (rec, False),
                 (f"{r.win_pct:.0f}%", True), (f"{r.margin:+.1f}", True)]
        gl = sorted(games.get(r.opp_user_id, []))
        det = ""
        if gl:
            grows = "".join(
                f"<tr><td>{yr}</td><td class='n'>{wk}</td>"
                f"<td class='n'>{pf:.1f}</td><td class='n'>{pa:.1f}</td>"
                f"<td class='n'>{pf - pa:+.1f}</td>"
                f"<td><span class='res "
                f"{'w' if res == 'W' else 'l' if res == 'L' else ''}'>{res}</span></td></tr>"
                for yr, wk, pf, pa, res in gl)
            det = ("<table class='dt-games'><thead><tr><th>Season</th>"
                   "<th class='n'>Wk</th><th class='n'>PF</th><th class='n'>PA</th>"
                   "<th class='n'>Margin</th><th>Result</th></tr></thead><tbody>"
                   + grows + "</tbody></table>")
        rows.append((cells, det))
    table = _drill_table(
        [("Opponent", False), ("Record", False), ("Win %", True), ("Avg margin", True)],
        "minmax(120px,1.5fr) 84px 64px 92px", rows)
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


def _game_log(s: Season, manager: str) -> str:
    """One manager's season game by game: opponent, result, points, margin."""
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
        res = str(r["result"]) if pd.notna(r.get("result")) else "—"
        cls = {"W": "w", "L": "l"}.get(res, "")
        pa = r.get("pa")
        pa_txt = f"{pa:.1f}" if pd.notna(pa) else "—"
        mg_txt = f"{r['points'] - pa:+.1f}" if pd.notna(pa) else "—"
        cells = [
            (str(wk), False),
            (html.escape(str(opp)) if opp else "— (no game)", False),
            (f"<span class='res {cls}'>{res}</span>", False),
            (f"{r['points']:.1f}", True), (pa_txt, True), (mg_txt, True)]
        # Per-week drill-down: labelled facts plus that week's full starting lineup.
        facts, lineup_tbl = [], ""
        wp = pl.iloc[0:0]
        if have_pl:
            wkall = pl[(pl["roster_id"] == rid) & (pl["week"] == wk)]
            wp = wkall[wkall["is_starter"]]
            bench = wkall[~wkall["is_starter"]]
            if not wp.empty:
                top = wp.loc[wp["points"].idxmax()]
                facts.append(("Top starter", _player_fact(top)))
                if len(wp) > 1:
                    cold = wp.loc[wp["points"].idxmin()]
                    facts.append(("Coldest starter", _player_fact(cold)))
            if not bench.empty:
                bh = bench.loc[bench["points"].idxmax()]
                if float(bh["points"]) > 0:
                    facts.append(("Best left on bench", _player_fact(bh)))
        if lu is not None:
            lr = lu[(lu["user_name"] == manager) & (lu["week"] == wk)]
            if len(lr):
                lr = lr.iloc[0]
                facts.append(("Optimal lineup",
                              f"<span class='pts'>{lr['optimal']:.1f}</span>"))
                facts.append(("Left on bench",
                              f"<span class='pts'>{lr['left_on_bench']:.1f}</span>"))
                # The stinger: a loss the best lineup would have won.
                if (pd.notna(pa) and float(r["points"]) < float(pa)
                        and float(lr["optimal"]) > float(pa)):
                    facts.append(("Coaching cost", "<span class='res l'>the optimal "
                                  "lineup would have won this</span>"))
        if not wp.empty:
            ws = assign_slots(wp, s.slots)
            started = _mini_table(
                [("Slot", False), ("Starter", False), ("Pts", True)],
                [[(html.escape(str(x["slot"])), False),
                  (f"<strong>{html.escape(str(x['player_name']))}</strong>", False),
                  (f"{float(x['points']):.1f}", True)] for _, x in ws.iterrows()])
            # …and what the best legal lineup from that roster would have been.
            opt_tbl, opt_total = "", None
            if s.slots and not wkall.empty:
                ol = optimal_lineup(wkall, s.slots)
                if len(ol):
                    opt_total = float(ol["points"].sum())
                    sids = set(wp["player_id"].astype(str))
                    # Re-label the same chosen players through assign_slots so
                    # both tables use one slot vocabulary and line up row for
                    # row. The player set (and so the total) is untouched.
                    ol = assign_slots(ol.drop(columns="slot"), s.slots)
                    opt_tbl = _mini_table(
                        [("Slot", False), ("Best available", False), ("Pts", True)],
                        [[(html.escape(str(x["slot"])), False),
                          (f"<strong>{html.escape(str(x['player_name']))}</strong>"
                           + ("" if str(x["player_id"]) in sids
                              else " <span class='q'>(was benched)</span>"), False),
                          (f"{float(x['points']):.1f}", True)]
                         for _, x in ol.iterrows()])
            lineup_tbl = (
                "<div class='dt-tables'>"
                + _labeled(f"Started · {float(r['points']):.1f} pts", started)
                + (_labeled(f"Optimal · {opt_total:.1f} pts", opt_tbl)
                   if opt_tbl else "")
                + "</div>")
        rows.append((cells, _facts(facts) + lineup_tbl))
    cols = [("Wk", False), ("Opponent", False), ("Result", False),
            ("PF", True), ("PA", True), ("Margin", True)]
    return _drill_table(cols, "34px minmax(90px,1.4fr) 64px 66px 66px 76px", rows)


def _position_mix(s: Season, manager: str) -> str:
    """Where one manager's started points came from, by position + league rank."""
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
    ours = starters[starters["roster_id"] == rid]
    rows = []
    for p in metrics.POSITIONS:
        if p not in pts:
            continue
        cells = [(p, False), (f"{pts[p]:.0f}", True),
                 (f"{pts[p] / total * 100:.0f}%", True),
                 (_rank_pill(int(rk[p]), n_teams), True)]
        # Drill: who actually produced those points at this position.
        sub = ours[ours["position"] == p]
        detail = ""
        if not sub.empty:
            g2 = (sub.groupby("player_name", as_index=False)
                  .agg(pts=("points", "sum"), starts=("points", "size"))
                  .sort_values("pts", ascending=False).head(8))
            detail = _mini_table(
                [("Player", False), ("Starts", True), ("Pts", True),
                 ("Share of pos", True)],
                [[(f"<strong>{html.escape(str(x.player_name))}</strong>", False),
                  (f"{int(x.starts)}", True), (f"{x.pts:.0f}", True),
                  (f"{x.pts / (pts[p] or 1) * 100:.0f}%", True)]
                 for x in g2.itertuples()])
        rows.append((cells, detail))
    return _drill_table(
        [("Position", False), ("Started pts", True), ("Share", True),
         ("League rank", True)],
        "70px 1fr 90px 110px", rows)


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
}


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
    if kind == "playoff":
        p = (playoffs or {}).get(s.season)
        return (p,) if p is not None else None
    return None


def report_parts(s: Season, seasons: dict | None = None,
                 playoffs: dict | None = None, manager: str | None = None) -> dict:
    """The report's content as data, so any surface can render it.

    Returns the headings, tiles, narrative, lead table and an ordered list of
    sections. Each section carries EITHER pre-built `html` (the manager tables)
    or a list of `charts` as `(chart_key, caption)` — the standalone file renders
    those keys to embedded PNGs, the dashboard tab points <img> at /chart/<key>.
    """
    scoped = bool(manager) and (s.standings["user_name"] == manager).any()
    if scoped:
        # A manager report stays about THEM -- their game log, where their points
        # came from, their own playoff run, and their own career -- rather than
        # restating the whole-league charts. The one cross-manager view kept is
        # the ranking table (their rank, plus the best/worst team per category).
        sections = [
            ("Week by week", "Their season game by game — expand a week for its detail.",
             _game_log(s, manager),
             [("mgr_score_band", "Weekly score against the league's range"),
              ("mgr_optimal", "Started vs optimal, and the running cost of the bench"),
              ("mgr_margins", "Margin by week — blowouts vs coin flips")]),
            ("Where the points came from", "Started points by position for this "
             "roster, and how each ranks in the league.", _position_mix(s, manager), []),
            ("Season standouts", "Who carried the team, and the best moves off the "
             "waiver wire and in trades.", _mgr_standouts(s, manager), []),
            ("Draft class", "How their draft paid off — steals and reaches.",
             _mgr_draft(s, manager), []),
            ("Trades & the waiver wire", "Every deal they made and every player "
             "they picked up — expand one for what it returned.",
             _mgr_transactions(s, manager), []),
            ("Rivalries", "Their record against the rest of the league — expand one "
             "for every meeting.", _mgr_rivalry(s, manager, seasons), []),
            ("Splits & awards", "The season sliced a few ways.",
             _mgr_splits(s, manager), []),
            ("Their postseason", "", _mgr_postseason(s, manager, playoffs), []),
            ("Their career", "", _mgr_career(s, manager, seasons), []),
        ]
        out = {
            "scoped": True, "eyebrow": "Manager report",
            "heading_text": str(manager), "subhead": f"{s.name} · {s.season}",
            "heading_html": (f"{html.escape(str(manager))}<br>"
                             f"<span class='subhead'>{html.escape(s.name)} · "
                             f"{s.season}</span>"),
            "title": f"{html.escape(str(manager))} · {s.season} Manager Report",
            "tiles": _manager_tiles(s, manager),
            "narrative": _manager_narrative(s, manager, seasons),
            "table_title": "Where they rank",
            "table_blurb": ("How they place in each category — their rank, and the "
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
            ("Coaching & scoring", "Who set the best lineups and who ran hot or cold.", "",
             [("efficiency", "Lineup efficiency"),
              ("consistency", "Weekly score distributions"),
              ("pf_pa", "Points for vs against")]),
            ("The weekly story", "How the table and the scoring moved week to week.", "",
             [("table_position", "Weekly table position"),
              ("team_points", "Weekly team points")]),
            ("Rosters & positions", "Where each team's points came from.", "",
             [("position_scoring", "Scoring by position"),
              ("roster_heatmap", "Roster construction"),
              ("flex_usage", "Flex allocation")]),
            ("Managers & transactions",
             "Roster-building style, and what the moves returned.", "",
             [("manager_profile", "Manager tendencies"),
              ("trade_performance", "Traded-player value"),
              ("waiver_performance", "Waiver / FA value")]),
        ]
        # Postseason scoped to THIS season's bracket; career context is explicitly
        # cross-season (the whole-league view is the point there).
        if playoffs and s.season in playoffs:
            sections.append(("The postseason",
                             "How this season's bracket actually played out.", "",
                             [("bracket", f"{s.season} playoff bracket")]))
        if seasons and len(seasons) > 1:
            sections.append(("Career context",
                             "This season against the league's whole history.", "",
                             [("career", "Career standings"),
                              ("trajectory", "Finish trajectory by season")]))
        out = {
            "scoped": False, "eyebrow": "Season report",
            "heading_text": s.name, "subhead": str(s.season),
            "heading_html": f"{html.escape(s.name)}<br>{s.season}",
            "title": f"{html.escape(s.name)} · {s.season} Season Report",
            "tiles": _tiles(s),
            "narrative": _md(summaries.summary_season(s)),
            "table_title": "Team by team",
            "table_blurb": ("The whole season on one line each — record, points for "
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
         "self_boxed": bool(re.search(r"(?:^|</p>)\s*<div class='(?:drilltable|draftboard)'", h))}
        for t, b, h, c in sections if h or c]
    return out


def season_report(s: Season, path: str, seasons: dict | None = None,
                  playoffs: dict | None = None, manager: str | None = None) -> str:
    """Write a standalone HTML season report for `s`; returns the path.

    `seasons` (the league's whole chain) adds career context; `playoffs` (stored
    brackets) adds the postseason section for the report's season. `manager`
    scopes the report to one team (see `report_parts`). Charts are baked in as
    base64 PNGs so the file stands alone.
    """
    parts = report_parts(s, seasons, playoffs, manager)
    tiles = "".join(
        f"<div class='tile'><span class='k'>{html.escape(k)}</span>"
        f"<span class='v'>{html.escape(str(v))}</span>"
        f"<span class='s'>{html.escape(str(sub))}</span></div>"
        for k, v, sub in parts["tiles"])

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
    doc = _TEMPLATE.format(
        title=parts["title"], eyebrow=parts["eyebrow"],
        heading=parts["heading_html"],
        generated=date.today().isoformat(),
        tiles=tiles, narrative=parts["narrative"],
        table_title=parts["table_title"], table_blurb=parts["table_blurb"],
        team_table=parts["table_html"],
        sections=body, css=_CSS)
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
/* A table whose rows each expand (native <details>, no script) to show detail. */
.drilltable{border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;
 background:var(--card)}
.dt-head,.dt-row>summary{display:grid;grid-template-columns:var(--cols);gap:10px;
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
.dt-detail{padding:15px 16px 17px;font-size:12.5px;color:var(--muted);
 border-top:1px solid var(--line);line-height:1.6;overflow-x:auto;
 background:color-mix(in srgb,var(--ink) 3.5%,transparent)}
.dt-detail strong{color:var(--ink)}
.dt-row .res.w{color:#2f9e44;font-weight:700}.dt-row .res.l{color:#e03131;font-weight:700}
/* Drill bodies are labelled fields / mini-tables, never a run-on sentence. */
.dt-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:18px 32px}
.fact{display:flex;flex-direction:column;gap:4px;min-width:0}
.fl{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);
 font-weight:700;line-height:1.3}
.fv{font-size:13.5px;color:var(--ink);line-height:1.45;white-space:normal;
 overflow-wrap:anywhere}
.fv .pos{color:var(--muted);font-size:11px;font-weight:600;margin:0 2px}
.fv .pts{font-variant-numeric:tabular-nums;font-weight:700}
table.dt-games{border-collapse:collapse;font-size:12.5px;width:auto;margin-top:2px}
.dt-detail .dt-facts+table.dt-games,.dt-detail .dt-facts+.dt-tables{margin-top:16px}
.dt-tables{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px 36px}
.dt-block{min-width:0}
.dt-sub{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);
 font-weight:700;margin-bottom:6px}
table.dt-games th{font-size:10px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--faint);font-weight:700;text-align:left;padding:0 26px 8px 0;border:0}
table.dt-games td{padding:7px 26px 7px 0;white-space:nowrap;border:0;color:var(--ink)}
table.dt-games tbody tr:not(:last-child) td{border-bottom:1px solid var(--line)}
table.dt-games th:last-child,table.dt-games td:last-child{padding-right:0}
table.dt-games td.n,table.dt-games th.n{text-align:right;font-variant-numeric:tabular-nums}
/* Stacked blocks inside one section need real separation. */
.teamsec table.teams+table.teams,.teamsec table.teams+.drilltable,
.teamsec table.teams+.dt-facts,.teamsec .drilltable+table.teams,
.teamsec .drilltable+.dt-facts,.teamsec .dt-facts+table.teams,
.teamsec .dt-facts+.drilltable{margin-top:26px}
.teamsec p.blurb{margin:2px 2px 14px}
.teamsec table.teams+p.blurb,.teamsec .drilltable+p.blurb{margin-top:20px}
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
"""

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body><div class="wrap">
<header class="top">
  <div><div class="eyebrow">{eyebrow}</div><h1>{heading}</h1></div>
  <div class="gen">Generated {generated}<br>Data: public Sleeper API</div>
</header>
<div class="tiles">{tiles}</div>
<div class="lead"><h2 style="border:0;padding:0;margin:14px 0 0">What the numbers say</h2>
{narrative}</div>
<section><h2>{table_title}</h2>
<p class="blurb">{table_blurb}</p>
<div class="teamsec">{team_table}</div></section>
{sections}
<footer><span>Champions come from the stored playoff brackets, not Sleeper&rsquo;s
winners_bracket.</span><span>sleepermetrics</span></footer>
</div></body></html>"""
