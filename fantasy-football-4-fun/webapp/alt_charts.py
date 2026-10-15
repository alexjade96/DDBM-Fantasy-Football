"""Chart prototypes for Player Analytics (shown on the Testing tab, not yet in the cards).

Small inline-SVG builders with no JavaScript library: a sparkline, horizontal share
bars, and a bar or line chart over the seasons.  They take plain lists and return
HTML strings, so they can be tested without a browser.  Colours come from the page's
CSS variables, so both themes work.  A missing value is a gap, never a zero.
"""
from __future__ import annotations

import math
from html import escape

from webapp import alt_analytics as aa

_ACCENT = "var(--turf)"
_MUTED = "var(--muted)"


def _num(v) -> float | None:
    return None if v is None or v != v else float(v)


def sparkline(values: list, width: int = 84, height: int = 22) -> str:
    """A tiny line over the values, with the last point marked.  A missing value
    breaks the line.  Fewer than two recorded values draws nothing."""
    vals = [_num(v) for v in values]
    have = [v for v in vals if v is not None]
    if len(have) < 2:
        return ""
    lo, hi = min(have), max(have)
    span = hi - lo or 1.0
    pad = 3
    n = len(vals)

    def xy(i: int, v: float) -> tuple[float, float]:
        x = pad + (width - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)
        y = height - pad - (height - 2 * pad) * ((v - lo) / span)
        return round(x, 1), round(y, 1)

    segs: list[list[tuple[float, float]]] = [[]]
    for i, v in enumerate(vals):
        if v is None:
            if segs[-1]:
                segs.append([])
        else:
            segs[-1].append(xy(i, v))
    lines = "".join(
        f'<polyline points="{" ".join(f"{x},{y}" for x, y in seg)}" fill="none" '
        f'stroke="{_ACCENT}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        for seg in segs if len(seg) > 1)
    last_i = max(i for i, v in enumerate(vals) if v is not None)
    cx, cy = xy(last_i, vals[last_i])
    return (f'<svg class="alt-spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}"'
            f' role="img" aria-label="trend">{lines}<circle cx="{cx}" cy="{cy}" r="2.2" fill="{_ACCENT}"/></svg>')


def hbars(items: list[tuple[str, float | None, str]], width: int = 420, row: int = 24) -> str:
    """Horizontal bars, one per (label, value, text), in the order given.  Bars start
    at zero and are scaled to the largest value; a missing value draws no bar."""
    items = [(l, _num(v), t) for l, v, t in items]
    if not any(v for _, v, _ in items):
        return ""
    top = max(v for _, v, _ in items if v is not None) or 1.0
    label_w, value_w = 132, 64
    bar_w = width - label_w - value_w - 8
    h = row * len(items) + 4
    out = [f'<svg class="alt-hbars" viewBox="0 0 {width} {h}" width="100%" role="img" aria-label="bars">']
    for n, (label, v, text) in enumerate(items):
        y = 2 + n * row
        out.append(f'<text x="{label_w - 6}" y="{y + row * 0.68:.1f}" text-anchor="end" font-size="12" '
                   f'fill="currentColor">{escape(str(label))}</text>')
        if v is not None and v > 0:
            w = max(1.0, bar_w * v / top)
            out.append(f'<rect x="{label_w}" y="{y + 3}" width="{w:.1f}" height="{row - 8}" rx="2" '
                       f'fill="{_ACCENT}" opacity="0.85"/>')
        out.append(f'<text x="{label_w + bar_w + 8}" y="{y + row * 0.68:.1f}" font-size="12" '
                   f'fill="{_MUTED}">{escape(text)}</text>')
    out.append("</svg>")
    return "".join(out)


def series_chart(labels: list[str], values: list, kind: str = "bar", width: int = 440,
                 height: int = 190, fmt=lambda v: f"{v:g}", fit: bool | None = None) -> str:
    """A bar or line chart over labelled points (seasons, usually).  Bars always start
    at zero so their length stays honest; a line is fitted to its own range by default
    (`fit=False` starts it at zero too), because a rate that moves between 5 and 10
    would otherwise sit flat at the top.  A missing value is a gap in the line and no
    bar.  X labels are thinned so they never overlap.  Raises ValueError for a kind
    other than bar or line."""
    if kind not in ("bar", "line"):
        raise ValueError(f"unknown chart kind: {kind}")
    vals = [_num(v) for v in values]
    have = [v for v in vals if v is not None]
    if not have:
        return ""
    fit = (kind == "line") if fit is None else fit
    if kind == "bar":
        fit = False
    hi, lo = max(have), min(have)
    if fit:
        span = (hi - lo) or abs(hi) or 1.0
        lo, hi = lo - span * 0.12, hi + span * 0.12
        if min(have) >= 0:
            lo = max(lo, 0.0)
    else:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
        if hi == lo:
            hi = lo + 1.0
    ml, mr, mt, mb = 40, 10, 12, 26
    pw, ph = width - ml - mr, height - mt - mb
    n = len(vals)
    step = pw / n
    every = max(1, -(-n * 30 // int(pw)))                     # a label at least ~30px apart

    def y(v: float) -> float:
        return mt + ph * (1 - (v - lo) / (hi - lo))

    out = [f'<svg class="alt-series" viewBox="0 0 {width} {height}" width="100%" role="img" '
           f'aria-label="{kind} chart">']
    for frac in (0.0, 0.5, 1.0):                                  # light guides: bottom, middle, top
        tick = lo + (hi - lo) * frac
        gy = y(tick)
        out.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{width - mr}" y2="{gy:.1f}" '
                   f'stroke="{_MUTED}" stroke-opacity="0.25"/>')
        out.append(f'<text x="{ml - 5}" y="{gy + 4:.1f}" text-anchor="end" font-size="10" '
                   f'fill="{_MUTED}">{escape(fmt(tick))}</text>')
    pts: list[list[tuple[float, float]]] = [[]]
    for i, v in enumerate(vals):
        cx = ml + step * (i + 0.5)
        if i % every == 0:
            out.append(f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle" font-size="10" '
                       f'fill="{_MUTED}">{escape(str(labels[i]))}</text>')
        if v is None:
            if pts[-1]:
                pts.append([])
            continue
        if kind == "bar":
            bw = step * 0.62
            out.append(f'<rect x="{cx - bw / 2:.1f}" y="{min(y(v), y(0)):.1f}" width="{bw:.1f}" '
                       f'height="{abs(y(0) - y(v)):.1f}" rx="2" fill="{_ACCENT}" opacity="0.85">'
                       f'<title>{escape(str(labels[i]))}: {escape(fmt(v))}</title></rect>')
        else:
            pts[-1].append((cx, y(v)))
            out.append(f'<circle cx="{cx:.1f}" cy="{y(v):.1f}" r="3" fill="{_ACCENT}">'
                       f'<title>{escape(str(labels[i]))}: {escape(fmt(v))}</title></circle>')
    if kind == "line":
        for seg in pts:
            if len(seg) > 1:
                out.insert(1, f'<polyline points="{" ".join(f"{x:.1f},{yy:.1f}" for x, yy in seg)}" '
                              f'fill="none" stroke="{_ACCENT}" stroke-width="2" stroke-linejoin="round"/>')
    out.append("</svg>")
    return "".join(out)


#: Series colours: distinguishable from each other and readable on a light or dark page.
PALETTE = ["#2f9e44", "#1c7ed6", "#f08c00", "#ae3ec9", "#e03131", "#0c8599", "#868e96"]
#: Groupings that read as a time series (one multi-line chart).
_TIME_GROUPS = {"season", "week"}
#: Peak-to-low ratio above which stats stop sharing one axis and are scaled one by one.
_SHARED_AXIS_RATIO = 3.0


def _compact(v: float) -> str:
    """A short axis number: 1.2k, 10, 7.5."""
    if abs(v) >= 10000:
        return f"{v / 1000:.0f}k"
    if abs(v) >= 1000:
        return f"{v / 1000:.1f}k".replace(".0k", "k")
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 or abs(v) >= 100 else f"{v:.1f}"


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Round tick values (1, 2, 2.5, 5 times a power of ten) covering lo to hi, about n of
    them.  The first is at or below lo and the last at or above hi."""
    span = (hi - lo) or abs(hi) or 1.0
    raw = span / max(n - 1, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag + 1e-12)
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    count = int(round((end - start) / step))
    return [round(start + i * step, 10) for i in range(count + 1)]


def _tick_decimals(ticks: list[float]) -> int:
    """Fewest decimals that print every tick exactly (0 to 3)."""
    for d in range(4):
        if all(abs(t * 10 ** d - round(t * 10 ** d)) < 1e-6 for t in ticks):
            return d
    return 3


def _short(text: str, limit: int = 22) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _legend(series: list[dict]) -> list[dict]:
    return [{"index": n, "label": sr["label"], "color": PALETTE[n % len(PALETTE)], "note": sr.get("note", "")}
            for n, sr in enumerate(series)]


def _spread_labels(items: list[tuple[float, int]], lo: float, hi: float, gap: float = 12.5) -> dict[int, float]:
    """Move label y positions apart so none is closer than `gap` px, staying in lo..hi.
    `items` is [(y, id)]; returns {id: y}."""
    order = sorted(items)
    ys = [y for y, _ in order]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    over = ys[-1] - hi if ys else 0
    if over > 0:
        ys = [y - over for y in ys]
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - gap)
    ys = [max(y, lo) for y in ys]
    return {ident: y for (_, ident), y in zip(order, ys)}


def _axis_swaps(cols: list[dict], ticks: list[float], pos, x_anchor: str, y_title: float, x_title: float,
                rotated: bool, title_default: str) -> str:
    """The axis labels of an index chart: the neutral percent labels (always shown) plus, per
    stat, the same ticks written in that stat's own units and colour with its name as the
    axis title.  The page script shows a stat's set while the stat is hovered (see
    `.alt-yl` in the page script), so no single stat is the axis by default.

    `pos(t)` gives the (x, y) of tick t; `x_anchor` is the text-anchor of the labels."""
    def title(text: str, color: str | None) -> str:
        fill = color or _MUTED
        weight = ' font-weight="600"' if color else ' font-style="italic"'
        if rotated:
            return (f'<text transform="rotate(-90 {x_title:.1f} {y_title:.1f})" x="{x_title:.1f}" y="{y_title + 3:.1f}" '
                    f'text-anchor="middle" font-size="10" fill="{fill}"{weight}>{escape(text)}</text>')
        return (f'<text x="{x_title:.1f}" y="{y_title:.1f}" text-anchor="middle" font-size="11" '
                f'fill="{fill}"{weight}>{escape(text)}</text>')

    def label(t: float, text: str, color: str | None) -> str:
        x, y = pos(t)
        fill = color or _MUTED
        weight = ' font-weight="600"' if color else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{x_anchor}" font-size="10" fill="{fill}"{weight}>'
                f'{escape(text)}</text>')

    out = ['<g class="alt-yl alt-yl-def">'
           + "".join(label(t, f"{t:.0f}%", None) for t in ticks) + title(title_default, None) + "</g>"]
    for n_s, c in enumerate(cols):
        color = PALETTE[n_s % len(PALETTE)]
        out.append(f'<g class="alt-yl" data-ys="{n_s}">'
                   + "".join(label(t, c["fmt"](t / 100.0 * c["mean"]), color) for t in ticks)
                   + title(c["label"], color) + "</g>")
    return "".join(out)


def multi_line(labels: list[str], series: list[dict], width: int = 600, height: int = 280,
               x_title: str | None = None) -> dict | None:
    """One chart with a line per stat over the same x points (seasons, usually).

    `series` is [{"key", "label", "values", "fmt"}].  Stats whose peaks are within
    _SHARED_AXIS_RATIO of each other share one axis in their own units ("shared").
    Otherwise every stat is drawn as a percent of its own average ("index": 100% is the
    player's average for that stat; a stat whose average is zero or negative is left out).
    An index chart's axis starts neutral, in percent, and turns into the hovered stat's own
    units (see `_axis_swaps`).  Round ticks and a gridline at each, the last point of every
    line carries its real value, and a lone line labels every point.  A stat with fewer than
    two recorded values is left out, a missing value is a gap, and the legend notes each
    stat's real range.  Returns {"svg", "legend", "mode"} or None when nothing can be drawn."""
    cols = []
    for sr in series:
        vals = [_num(v) for v in sr["values"]]
        have = [v for v in vals if v is not None]
        if len(have) >= 2:
            cols.append({**sr, "vals": vals, "lo": min(have), "hi": max(have), "mean": sum(have) / len(have)})
    if not cols or len(labels) < 2:
        return None
    peaks = [c["hi"] for c in cols if c["hi"] > 0]
    shared = (len(cols) == 1 or (len(peaks) == len(cols) and min(c["lo"] for c in cols) >= 0
                                 and max(peaks) / min(peaks) <= _SHARED_AXIS_RATIO))
    if not shared:
        cols = [c for c in cols if c["mean"] > 0]
        if not cols:
            return None

    def plotted(c: dict, v: float) -> float:
        return v if shared else v / c["mean"] * 100.0

    pv = [plotted(c, v) for c in cols for v in c["vals"] if v is not None]
    lo, hi = min(pv), max(pv)
    span = (hi - lo) or abs(hi) or 1.0
    plo, phi = lo - span * 0.08, hi + span * 0.08
    if lo >= 0:
        plo = max(plo, 0.0)
    ticks = _nice_ticks(plo, phi, 5)
    glo, ghi = ticks[0], ticks[-1]
    decimals = _tick_decimals(ticks)
    if shared:
        texts = [f"{t:,.{decimals}f}" for t in ticks]
    else:
        texts = [f"{t:.0f}%" for t in ticks] + [c["fmt"](t / 100.0 * c["mean"]) for c in cols for t in ticks]
    ml = max(40, 7 * max(len(t) for t in texts) + 14) + (14 if not shared else 0)
    mr, mt, mb = 58, 14, 26 + (14 if x_title else 0)
    height = height + (14 if x_title else 0)
    pw, ph = width - ml - mr, height - mt - mb
    n = len(labels)
    step = pw / n
    every = max(1, -(-n * 34 // int(pw)))

    def gy_of(t: float) -> float:
        return mt + ph * (1 - (t - glo) / (ghi - glo))

    def y(c: dict, v: float) -> float:
        return gy_of(plotted(c, v))

    out = [f'<svg class="alt-multi" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="line chart">']
    for t in ticks:
        out.append(f'<line x1="{ml}" y1="{gy_of(t):.1f}" x2="{width - mr}" y2="{gy_of(t):.1f}" '
                   f'stroke="{_MUTED}" stroke-opacity="0.25"/>')
    if shared:
        for t, text in zip(ticks, texts):
            out.append(f'<text x="{ml - 5}" y="{gy_of(t) + 3.5:.1f}" text-anchor="end" font-size="10" '
                       f'fill="{_MUTED}">{escape(text)}</text>')
    else:
        out.append(f'<line x1="{ml}" y1="{gy_of(100.0):.1f}" x2="{width - mr}" y2="{gy_of(100.0):.1f}" '
                   f'stroke="currentColor" stroke-opacity="0.55" stroke-dasharray="4 3">'
                   f'<title>The player\'s own average</title></line>')
        out.append(_axis_swaps(cols, ticks, lambda t: (ml - 5, gy_of(t) + 3.5), "end", mt + ph / 2, 11,
                               True, "% of own average"))
    out.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + ph}" stroke="{_MUTED}" stroke-opacity="0.4"/>')
    for i, lab in enumerate(labels):
        if i % every == 0:
            out.append(f'<text x="{ml + step * (i + 0.5):.1f}" y="{mt + ph + 14}" text-anchor="middle" '
                       f'font-size="10" fill="{_MUTED}">{escape(str(lab))}</text>')
    if x_title:
        out.append(f'<text x="{ml + pw / 2:.1f}" y="{height - 4}" text-anchor="middle" font-size="10" '
                   f'fill="{_MUTED}" font-style="italic">{escape(x_title)}</text>')
    ends = {}
    for n_s, c in enumerate(cols):
        last = max(i for i, v in enumerate(c["vals"]) if v is not None)
        ends[n_s] = (y(c, c["vals"][last]), last)
    end_y = _spread_labels([(yy, k) for k, (yy, _) in ends.items()], mt + 4, mt + ph + 4)
    for n_s, c in enumerate(cols):
        color = PALETTE[n_s % len(PALETTE)]
        segs: list[list[tuple[float, float]]] = [[]]
        dots = []
        notes = []
        for i, v in enumerate(c["vals"]):
            if v is None:
                if segs[-1]:
                    segs.append([])
                continue
            cx, cy = ml + step * (i + 0.5), y(c, v)
            segs[-1].append((cx, cy))
            pct = "" if shared else f' ({v / c["mean"] * 100:.0f}% of his average)'
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{color}"><title>'
                        f'{escape(str(labels[i]))}: {escape(c["label"])} {escape(c["fmt"](v))}{pct}</title></circle>')
            if len(cols) == 1 and n <= 12 and i != ends[n_s][1]:
                notes.append(f'<text x="{cx:.1f}" y="{cy - 8:.1f}" text-anchor="middle" font-size="10" '
                             f'fill="{color}">{escape(c["fmt"](v))}</text>')
        lines = "".join(f'<polyline points="{" ".join(f"{x:.1f},{yy:.1f}" for x, yy in seg)}" fill="none" '
                        f'stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
                        for seg in segs if len(seg) > 1)
        last_x = ml + step * (ends[n_s][1] + 0.5)
        notes.append(f'<text x="{last_x + 7:.1f}" y="{end_y[n_s] + 3.5:.1f}" font-size="10" font-weight="600" '
                     f'fill="{color}">{escape(c["fmt"](c["vals"][ends[n_s][1]]))}</text>')
        out.append(f'<g class="alt-s" data-s="{n_s}">{lines}{"".join(dots)}{"".join(notes)}</g>')
    out.append("</svg>")
    legend = _legend([{"label": c["label"], "note": f'{c["fmt"](c["lo"])} to {c["fmt"](c["hi"])}'} for c in cols])
    return {"svg": "".join(out), "legend": legend, "mode": "shared" if shared else "index"}


def _bar_cols(series: list[dict]) -> list[dict]:
    """The stats a bar chart can draw: two or more recorded values, one of them positive.
    `mean` is the series' own "mean" when given (the caller's whole table), else the mean of
    the values passed."""
    cols = []
    for sr in series:
        vals = [_num(v) for v in sr["values"]]
        have = [v for v in vals if v is not None]
        if len(have) >= 2 and any(v > 0 for v in have):
            mean = sr.get("mean")
            cols.append({**sr, "vals": vals, "top": max(have),
                         "mean": mean if mean is not None else sum(have) / len(have)})
    return cols


def _bars_share_axis(cols: list[dict]) -> bool:
    peaks = [c["top"] for c in cols]
    return len(cols) == 1 or max(peaks) / min(peaks) <= _SHARED_AXIS_RATIO


def multi_bars(labels: list[str], series: list[dict], width: int = 600, x_title: str | None = None,
               games: list | None = None) -> dict | None:
    """Horizontal bars: a row per label, a bar per stat in the row, the real value written at
    the end of every bar, and a bottom axis with round ticks and a gridline at each.

    Stats whose peaks are within _SHARED_AXIS_RATIO of each other share one axis in their own
    units ("shared", titled with the stat names).  Otherwise each bar is drawn as a percent of
    its stat's average ("index": 100% is that stat's average, the dashed line; a stat whose
    average is not positive is left out); the axis starts neutral, in percent, and becomes the
    hovered stat's own units (see `_axis_swaps`).  Rows are banded, long labels are shortened
    (the tooltip has the full name and the games played, and the row says "12 g"), and a missing
    or negative value draws no bar.  Returns {"svg", "legend", "mode"} or None when no stat has
    a positive value."""
    cols = _bar_cols(series)
    if not cols or not labels:
        return None
    shared = _bars_share_axis(cols)
    if not shared:
        cols = [c for c in cols if c["mean"] > 0]
        if not cols:
            return None
    for c in cols:
        c["note"] = f'largest {c["fmt"](c["top"])}'

    def plotted(c: dict, v: float) -> float:
        return v if shared else v / c["mean"] * 100.0

    ticks = _nice_ticks(0.0, max(plotted(c, v) for c in cols for v in c["vals"] if v is not None), 5)
    dom = ticks[-1]
    decimals = _tick_decimals(ticks)
    k = len(cols)
    rows_n = len(labels)
    bar_h = {1: 15, 2: 12}.get(k, 11 if k <= 5 else 10)
    if rows_n > 16:
        bar_h = min(bar_h, 12 if k == 1 else 10)
    label_w, value_w, mt = 168, 62, 22
    plot_w = width - label_w - value_w
    row_h = bar_h * k + 12
    body_h = row_h * rows_n
    h = mt + body_h + 40
    out = [f'<svg class="alt-multi alt-gbars" viewBox="0 0 {width} {h}" width="100%" role="img" aria-label="bar chart">']
    for r in range(rows_n):
        if r % 2 == 0:
            out.append(f'<rect class="band" x="0" y="{mt + r * row_h}" width="{width}" height="{row_h}" '
                       f'fill="currentColor" opacity="0.05"/>')
    for t in ticks:
        gx = label_w + plot_w * t / dom
        out.append(f'<line x1="{gx:.1f}" y1="{mt}" x2="{gx:.1f}" y2="{mt + body_h + 4}" '
                   f'stroke="{_MUTED}" stroke-opacity="0.25"/>')
    out.append(f'<line x1="{label_w}" y1="{mt + body_h}" x2="{label_w + plot_w}" y2="{mt + body_h}" '
               f'stroke="currentColor" stroke-opacity="0.35"/>')
    axis_y, title_x = mt + body_h + 17, label_w + plot_w / 2
    if shared:
        for t in ticks:
            out.append(f'<text x="{label_w + plot_w * t / dom:.1f}" y="{axis_y}" text-anchor="middle" font-size="10" '
                       f'fill="{_MUTED}">{t:,.{decimals}f}</text>')
        out.append(f'<text x="{title_x:.1f}" y="{h - 5}" text-anchor="middle" font-size="11" fill="{_MUTED}">'
                   f'{escape(" / ".join(c["label"] for c in cols))}</text>')
    else:
        gx_100 = label_w + plot_w * 100.0 / dom
        out.append(f'<line x1="{gx_100:.1f}" y1="{mt}" x2="{gx_100:.1f}" y2="{mt + body_h}" stroke="currentColor" '
                   f'stroke-opacity="0.55" stroke-dasharray="4 3"><title>The stat\'s own average</title></line>')
        out.append(_axis_swaps(cols, ticks, lambda t: (label_w + plot_w * t / dom, axis_y), "middle", h - 5,
                               title_x, False, "% of each stat's average"))
    if x_title:
        out.append(f'<text x="{label_w - 8}" y="{mt - 8}" text-anchor="end" font-size="10" fill="{_MUTED}" '
                   f'font-style="italic">{escape(x_title)}</text>')
    out.append(f'<line x1="{label_w}" y1="{mt}" x2="{label_w}" y2="{mt + body_h}" '
               f'stroke="currentColor" stroke-opacity="0.35"/>')
    for r, lab in enumerate(labels):
        g = games[r] if games and games[r] is not None else None
        tip = str(lab) + (f" ({g} games)" if g is not None else "")
        count = f'<tspan fill="{_MUTED}" font-size="10">  {g} g</tspan>' if g is not None else ""
        out.append(f'<text x="{label_w - 8}" y="{mt + r * row_h + row_h / 2 + 4:.1f}" text-anchor="end" '
                   f'font-size="12" fill="currentColor"><title>{escape(tip)}</title>'
                   f'{escape(_short(str(lab), 18))}{count}</text>')
    for n_s, c in enumerate(cols):
        color = PALETTE[n_s % len(PALETTE)]
        parts = []
        for r, v in enumerate(c["vals"]):
            if v is None or v <= 0:
                continue
            y0 = mt + r * row_h + 6 + n_s * bar_h
            w = max(1.0, plot_w * plotted(c, v) / dom)
            text = escape(c["fmt"](v))
            pct = "" if shared else f' ({v / c["mean"] * 100:.0f}% of the average)'
            parts.append(f'<rect class="bar" x="{label_w}" y="{y0}" width="{w:.1f}" height="{bar_h - 2}" '
                         f'rx="1.5" fill="{color}"><title>{escape(str(labels[r]))}: '
                         f'{escape(c["label"])} {text}{pct}</title></rect>')
            parts.append(f'<text x="{label_w + w + 5:.1f}" y="{y0 + bar_h - 3.5:.1f}" font-size="{9 if bar_h < 12 else 11}" '
                         f'fill="currentColor">{text}</text>')
        out.append(f'<g class="alt-s" data-s="{n_s}">{"".join(parts)}</g>')
    out.append("</svg>")
    return {"svg": "".join(out), "legend": _legend(cols), "mode": "shared" if shared else "index"}


#: Most rows any bar chart draws.
MAX_BAR_ROWS = 40


def _ranked(values: list, limit: int) -> list[int]:
    """Row indexes by value, largest first (a missing value last), at most `limit`."""
    order = sorted(range(len(values)), key=lambda i: -(values[i] if values[i] is not None else float("-inf")))
    return order[:limit]


def card_charts(result: dict) -> dict | None:
    """The Chart view of a card, from a `run_query` result (total row left out).

    A season or week grouping is a multi-line chart (see `multi_line`).  Any other grouping
    is horizontal bars of up to MAX_BAR_ROWS rows, every stat in the same chart, ranked by
    the first stat (see `multi_bars`; the average each bar is compared with is over every
    row, not just the ones drawn).  Both come with a legend whose entries switch a stat on
    or off and, in an index chart, hovering a stat puts the axis in its units.  Returns
    {"kind", "svg", "legend", "mode", ...} (bars also carry "shown", "of", "agg") or None
    with fewer than two rows or nothing drawable."""
    rows = result["rows"]
    group = result["spec"]["group_by"]
    if len(rows) < 2:
        return None
    labels = [aa.group_label(group, r["group"]) for r in rows]
    games = [r.get("games") for r in rows]
    series = [{"key": c["key"], "label": c["label"], "values": [r.get(c["key"]) for r in rows],
               "fmt": (lambda v, k=c["key"]: aa.format_value(k, v))} for c in result["columns"]]
    if group in _TIME_GROUPS:
        ch = multi_line(labels, series, x_title=aa.GROUPS.get(group))
        return {"kind": "series", **ch} if ch else None
    for sr in series:
        have = [_num(v) for v in sr["values"] if _num(v) is not None]
        sr["mean"] = sum(have) / len(have) if have else None
    keep = _ranked(series[0]["values"], MAX_BAR_ROWS)
    ch = multi_bars([labels[i] for i in keep],
                    [{**sr, "values": [sr["values"][i] for i in keep]} for sr in series],
                    x_title=aa.GROUPS.get(group), games=[games[i] for i in keep])
    if not ch:
        return None
    return {"kind": "bars", **ch, "shown": len(keep), "of": len(rows), "agg": result["spec"].get("agg")}


# -- the Testing-tab demo ---------------------------------------------------------------

def prototypes(games, position: str | None) -> dict:
    """Everything the Testing section shows for one player, from the same cards the
    dashboard runs: a season table with a sparkline under each column, a share-bar
    chart of targets (or attempts) by coverage, and a bar or line chart of one
    per-game column by season.  Pieces with no data are None."""
    out = {"spark": None, "share": None, "series": None}
    if games is None or games.empty:
        return out
    wl = aa.run_card(games, position, "workload", {})
    rows = wl["rows"]
    keys = [c["key"] for c in wl["columns"]]
    if len(rows) >= 2 and keys:
        cols = [{"label": c["label"], "spark": sparkline([r.get(c["key"]) for r in rows])}
                for c in wl["columns"]]
        out["spark"] = {"columns": cols, "view": aa.table_view(wl)}
        first = wl["columns"][0]
        out["series"] = {"label": first["label"],
                         "bar": series_chart([str(r["group"]) for r in rows],
                                             [r.get(first["key"]) for r in rows], "bar",
                                             fmt=lambda v: f"{v:.1f}"),
                         "line": series_chart([str(r["group"]) for r in rows],
                                              [r.get(first["key"]) for r in rows], "line",
                                              fmt=lambda v: f"{v:.1f}")}
    if any(c["id"] == "coverage" for c in aa.cards_for(position)):
        cv = aa.run_card(games, position, "coverage", {})
        key = cv["columns"][0]["key"] if cv["columns"] else None
        if key and cv["rows"] and aa.has_data(cv):
            items = sorted(((str(r["group"]), r.get(key), aa.format_value(key, r.get(key)))
                            for r in cv["rows"]), key=lambda t: -(t[1] or 0))
            out["share"] = {"label": cv["columns"][0]["label"], "svg": hbars(items)}
    return out
