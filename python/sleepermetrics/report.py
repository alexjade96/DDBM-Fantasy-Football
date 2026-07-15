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
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import metrics, plots, summaries  # noqa: E402
from .season import Season  # noqa: E402


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


def _team_table(s: Season) -> str:
    """One row per manager: the season on a line."""
    st = s.standings[["user_name", "wins", "losses", "points", "pa", "final_position"]]
    ap = metrics.allplay(s)[["user_name", "allplay_pct", "rank_delta"]]
    pw = metrics.power_rank(s)[["user_name", "power_rank"]]
    mp = metrics.manager_profile(s)[["user_name", "moves", "trades", "lineup_iq"]]
    d = (st.merge(ap, on="user_name").merge(pw, on="user_name").merge(mp, on="user_name")
         .sort_values("final_position"))
    rows = []
    for _, r in d.iterrows():
        gap = "even" if r["rank_delta"] == 0 else f"{r['rank_delta']:+d}"
        rows.append(
            f"<tr><td class='rank'>{int(r['final_position'])}</td>"
            f"<td class='name'>{html.escape(str(r['user_name']))}</td>"
            f"<td>{int(r['wins'])}-{int(r['losses'])}</td>"
            f"<td class='n'>{r['points']:.0f}</td>"
            f"<td class='n'>{r['pa']:.0f}</td>"
            f"<td class='n'>{r['allplay_pct'] * 100:.0f}%</td>"
            f"<td class='n'>#{int(r['power_rank'])}</td>"
            f"<td class='n'>{r['lineup_iq']:.0f}%</td>"
            f"<td class='n'>{int(r['moves'])}/{int(r['trades'])}</td></tr>")
    return (
        "<table class='teams'><thead><tr>"
        "<th>#</th><th>Manager</th><th>Record</th><th class='n'>PF</th>"
        "<th class='n'>PA</th><th class='n'>All-play</th><th class='n'>Power</th>"
        "<th class='n'>Lineup IQ</th><th class='n'>Moves/Trades</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _section(title, blurb, *figs) -> str:
    body = "".join(f for f in figs if f)
    if not body:
        return ""
    sub = f"<p class='blurb'>{html.escape(blurb)}</p>" if blurb else ""
    return f"<section><h2>{html.escape(title)}</h2>{sub}<div class='grid'>{body}</div></section>"


def season_report(s: Season, path: str, seasons: dict | None = None,
                  playoffs: dict | None = None) -> str:
    """Write a standalone HTML season report for `s`; returns the path.

    `seasons` (the league's whole chain) adds career context; `playoffs` (stored
    brackets) adds the postseason section for the report's season.
    """
    tiles = "".join(
        f"<div class='tile'><span class='k'>{html.escape(k)}</span>"
        f"<span class='v'>{html.escape(str(v))}</span>"
        f"<span class='s'>{html.escape(str(sub))}</span></div>"
        for k, v, sub in _tiles(s))

    sections = [
        _section("The standings", "Where the season finished, and how deserved it was.",
                 _fig(plots.plot_standings, s, _desc="Final standings"),
                 _fig(plots.plot_power_rank, s, _desc="Composite power ranking"),
                 _fig(plots.plot_allplay, s, _desc="All-play: standings independent of schedule"),
                 _fig(plots.plot_luck, s, _desc="Luck: actual vs all-play expected wins")),
        _section("Coaching & scoring", "Who set the best lineups and who ran hot or cold.",
                 _fig(plots.plot_efficiency, s, _desc="Lineup efficiency"),
                 _fig(plots.plot_consistency, s, _desc="Weekly score distributions"),
                 _fig(plots.plot_pf_pa, s, _desc="Points for vs against")),
        _section("The weekly story", "How the table and the scoring moved week to week.",
                 _fig(plots.plot_table_position, s, _desc="Weekly table position"),
                 _fig(plots.plot_team_points, s, _desc="Weekly team points")),
        _section("Rosters & positions", "Where each team's points came from.",
                 _fig(plots.plot_position_scoring, s, _desc="Scoring by position"),
                 _fig(plots.plot_roster_heatmap, s, _desc="Roster points heatmap"),
                 _fig(plots.plot_starter_bench, s, _desc="Starters vs bench")),
        _section("Managers & transactions", "Roster-building style, and what the moves returned.",
                 _fig(plots.plot_manager_profile, s, _desc="Manager tendencies"),
                 _fig(plots.plot_trade_performance, s, _desc="Traded-player value"),
                 _fig(plots.plot_waiver_performance, s, _desc="Waiver / FA value")),
    ]

    if playoffs and s.season in playoffs:
        p = playoffs[s.season]
        sections.append(_section(
            "The postseason", "How the bracket actually played out.",
            _fig(plots.plot_playoff_bracket, p, _desc="Playoff bracket"),
            _fig(plots.plot_playoff_players, playoffs, _desc="Best playoff players (all time)")))

    if seasons and len(seasons) > 1:
        sections.append(_section(
            "Career context", "This season against the league's whole history.",
            _fig(plots.plot_career, seasons, _desc="Career standings"),
            _fig(plots.plot_trajectory, seasons, _desc="Finish trajectory by season")))

    narrative = _md(summaries.summary_season(s))
    body = "".join(sec for sec in sections if sec)
    doc = _TEMPLATE.format(
        title=f"{html.escape(s.name)} · {s.season} Season Report",
        league=html.escape(s.name), season=s.season,
        generated=date.today().isoformat(),
        tiles=tiles, narrative=narrative, team_table=_team_table(s),
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
table.teams tbody tr:last-child td{border-bottom:0}
table.teams tbody tr:first-child td{background:color-mix(in srgb,var(--gold) 10%,transparent)}
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
  <div><div class="eyebrow">Season Report</div><h1>{league}<br>{season}</h1></div>
  <div class="gen">Generated {generated}<br>Data: public Sleeper API</div>
</header>
<div class="tiles">{tiles}</div>
<div class="lead"><h2 style="border:0;padding:0;margin:14px 0 0">What the numbers say</h2>
{narrative}</div>
<section><h2>Team by team</h2>
<p class="blurb">The whole season on one line each &mdash; record, points for and
against, all-play win %, power rank, lineup efficiency, and waiver moves / trades.</p>
<div class="teamsec">{team_table}</div></section>
{sections}
<footer><span>Champions come from the stored playoff brackets, not Sleeper&rsquo;s
winners_bracket.</span><span>sleepermetrics</span></footer>
</div></body></html>"""
