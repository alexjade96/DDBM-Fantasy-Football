#!/usr/bin/env python
"""Play one user's visit to a page against the running dev server and add up
the network calls each request caused.

    python tools/dev/loadmeter_journey.py player 4034 [--league ID] [--games N] [--cold] [--host http://127.0.0.1:8000]
    python tools/dev/loadmeter_journey.py url /team/DET

It is a testing tool, not part of the app.  The server measures itself
(`webapp.loadmeter`, on by default locally and off on Render) and reports each
request in `X-Load-Calls` / `X-Load-MB` / `X-Load-Net-Seconds` headers and at
`/loadmeter`; this script only drives the requests a browser would make and
reads those numbers back.  Run the server on port 8000 (the only port this
project uses).

What it follows: the page itself (including the loader redirect), every
`<img src="/chart/...">` and `hx-get` URL found in the HTML (those a browser
fetches on its own), and with `--games N` the first N game-detail drilldowns
(a browser fetches those only when a row is clicked).  It does not run
JavaScript, so a URL built by a script is not followed.

`--cold` adds `refresh=1` to the page request, which asks the app to rebuild
the profile.  That can trigger large downloads.  Without it you measure
whatever state the server's caches are in, which is also worth knowing.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time

import requests

_IMG = re.compile(r'<img[^>]+src="(/chart/[^"]+)"')
_HX = re.compile(r'hx-get="([^"]+)"([^>]*)>')
_REPLACE = re.compile(r'location\.replace\("([^"]+)"\)')


def _urls(page: str, games: int) -> list[str]:
    found: list[str] = []
    for m in _IMG.finditer(page):
        found.append(html.unescape(m.group(1)))
    game_n = 0
    for m in _HX.finditer(page):
        url, rest = html.unescape(m.group(1)), m.group(2)
        if "toggle once" in rest or "/game/" in url:
            if game_n >= games:
                continue            # only fetched on a click
            game_n += 1
        found.append(url)
    seen, out = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _get(host: str, url: str, rows: list, label: str | None = None) -> str:
    t0 = time.perf_counter()
    r = requests.get(host + url, timeout=600)
    secs = time.perf_counter() - t0
    rows.append({
        "url": label or url, "status": r.status_code, "seconds": secs,
        "calls": int(r.headers.get("X-Load-Calls", -1)),
        "mb": float(r.headers.get("X-Load-MB", -1)),
        "net": float(r.headers.get("X-Load-Net-Seconds", -1)),
        "cache": r.headers.get("X-Cache", ""),
    })
    return r.text


def run(host: str, start: str, games: int) -> list[dict]:
    rows: list[dict] = []
    page = _get(host, start, rows)
    redirect = _REPLACE.search(page)
    if redirect:                       # the loader page; a browser follows it
        page = _get(host, html.unescape(redirect.group(1)), rows)
    for url in _urls(page, games):
        _get(host, url, rows)
    return rows


def show(rows: list[dict]) -> None:
    if rows and rows[0]["calls"] < 0:
        print("The server sent no X-Load-* headers.  Is the meter on?  It is "
              "off on Render, or with LOADMETER=0, and the server must have "
              "restarted onto the new code.")
    print(f"{'status':>6} {'secs':>6} {'calls':>5} {'MB':>7} {'net s':>6}  url")
    for r in rows:
        print(f"{r['status']:>6} {r['seconds']:>6.1f} {r['calls']:>5} "
              f"{r['mb']:>7.2f} {r['net']:>6.1f}  {r['url'][:100]}")
    good = [r for r in rows if r["calls"] >= 0]
    print(f"\n{len(rows)} requests, {sum(r['calls'] for r in good)} network calls, "
          f"{sum(r['mb'] for r in good):.2f} MB, "
          f"{sum(r['seconds'] for r in rows):.1f}s wall")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kind", choices=["player", "url"])
    ap.add_argument("target", help="a player id, or a path for `url`")
    ap.add_argument("--league")
    ap.add_argument("--games", type=int, default=0)
    ap.add_argument("--cold", action="store_true")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    if not a.host.rstrip("/").endswith(":8000"):
        print("This project uses port 8000 only.")
        return 2
    if a.kind == "player":
        q = []
        if a.league:
            q.append(f"league={a.league}")
        if a.cold:
            q.append("refresh=1")
        start = f"/player/{a.target}" + (("?" + "&".join(q)) if q else "")
    else:
        start = a.target
    show(run(a.host.rstrip("/"), start, a.games))
    return 0


if __name__ == "__main__":
    sys.exit(main())
