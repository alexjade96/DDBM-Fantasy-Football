"""Single-week metrics + recap text (mirrors R weekly.R)."""
from __future__ import annotations

from .metrics import week_stats
from .season import Season


def summary_week(s: Season, week: int | None = None) -> str:
    """Markdown recap for one week."""
    wk = week if week is not None else s.last_week
    d = week_stats(s, wk)
    top = d.iloc[0]
    low = d.iloc[-1]
    bust = d.loc[d["left_on_bench"].idxmax()]
    lines = [
        f"### {s.name} - Week {wk} recap", "",
        f"- \U0001F525 **Top score:** {top['user_name']} ({top['points']:.1f})",
        f"- \U0001F9CA **Low score:** {low['user_name']} ({low['points']:.1f})",
    ]
    played = d[(d["result"].notna()) & (d["result"] != "T") & (d["margin"] > 0)]
    if len(played):
        blow = played.loc[played["margin"].idxmax()]
        close = played.loc[played["margin"].idxmin()]
        lines += [
            f"- \U0001F4A5 **Biggest blowout:** {blow['user_name']} by {blow['margin']:.1f}",
            f"- \U0001F630 **Closest game:** {close['user_name']} won by {close['margin']:.1f}",
        ]
    lines.append(
        f"- \U0001FA91 **Biggest bench blunder:** {bust['user_name']} left "
        f"{bust['left_on_bench']:.1f} pts on the bench")
    return "\n".join(lines)
