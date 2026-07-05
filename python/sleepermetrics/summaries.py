"""Auto-generated markdown insight text (mirrors R summaries.R)."""
from __future__ import annotations

from . import metrics
from .season import Season


def summary_season(s: Season) -> str:
    st = s.standings
    lead = st.iloc[0]
    lk = metrics.luck(s)
    lucky, unlucky = lk.iloc[0], lk.iloc[-1]
    eff = metrics.efficiency(s)
    best_c, worst_c = eff.iloc[0], eff.iloc[-1]
    hi = st.loc[st["highs"].idxmax()]
    cons = metrics.consistency(s)
    steady, swingy = cons.iloc[0], cons.iloc[-1]
    champ = " and the champion \U0001F451" if lead["champion"] else ""
    return "\n".join([
        f"### {s.season} season - what the numbers say", "",
        f"- **Top of the table:** **{lead['user_name']}** "
        f"({lead['wins']}-{lead['losses']}, {round(lead['points'])} pts{champ}).",
        f"- **Luckiest:** **{lucky['user_name']}** won {lucky['luck']:+.1f} games above "
        f"all-play expectation; **unluckiest:** **{unlucky['user_name']}** "
        f"({unlucky['luck']:+.1f}).",
        f"- **Best coach:** **{best_c['user_name']}** started {best_c['eff']:.1f}% of their "
        f"optimal lineup; **most left on the bench:** **{worst_c['user_name']}** "
        f"({round(worst_c['bench'])} pts wasted).",
        f"- **Weekly high-score crowns:** **{hi['user_name']}** led the league in scoring "
        f"{hi['highs']} week(s).",
        f"- **Steadiest:** **{steady['user_name']}** (SD {round(steady['sd'])}); "
        f"**boom-or-bust:** **{swingy['user_name']}** (SD {round(swingy['sd'])}).",
    ])


def summary_career(seasons: dict) -> str:
    ct = metrics.career(seasons)
    vets = ct[ct["seasons"] == ct["seasons"].max()]
    best = ct.iloc[0]
    most_t = ct.loc[ct["titles"].idxmax()]
    worst = ct.iloc[-1]
    return "\n".join([
        "### Career - across all seasons", "",
        f"- **Managers tracked:** {len(ct)} ({int((ct['seasons'] > 1).sum())} multi-season).",
        f"- **Best win %:** **{best['user_name']}** ({best['win_pct']}%, {best['record']}).",
        f"- **Most titles:** **{most_t['user_name']}** with {int(most_t['titles'])}.",
        f"- **Longest-tenured:** "
        + ", ".join(f"**{n}**" for n in vets['user_name'])
        + f" ({int(ct['seasons'].max())} seasons).",
        f"- **Still chasing a winning record:** **{worst['user_name']}** ({worst['win_pct']}%).",
    ])
