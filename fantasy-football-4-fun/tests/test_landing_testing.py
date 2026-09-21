"""Network-free tests for the landing-page Testing tab (league-free
counterpart to the loaded-dashboard Testing tab, tab_testing.html -- see
webapp/app.py's landing_testing() docstring and
webapp/templates/_landing_testing.html's own module comment).
Direct-call convention (no ASGI/TestClient layer), same as
test_playercompare_landing.py.

This page's original content was a set of Player Comparison layout demos
(chip strip, row highlight, grouped controls, sticky action bar, and a
chips+sticky combo). All were resolved -- row highlight, grouped controls,
and the chip strip were promoted to the real, live Player Comparison tab
(see test_playercompare_landing.py for coverage of those); the sticky-bar
and combo variants were tried and dropped. Per user request, once the last
demo was promoted, ALL of them were removed from this page entirely -- it
is not kept as a read-only archive. These tests cover the resulting empty
placeholder state, not the old demos.
"""
from __future__ import annotations


class _Req:
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


def test_landing_testing_registered_on_home_nav():
    from webapp import app
    body = (app.BASE / "templates" / "home.html").read_text(encoding="utf-8")
    assert "/testing" in body
    assert ">Testing<" in body


def test_landing_testing_route_renders():
    from webapp import app
    resp = app.landing_testing(_Req())
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "Testing" in body
    assert "Prototypes under review" in body


def test_landing_testing_player_comparison_demos_are_fully_removed():
    """Regression guard: every Player Comparison layout demo that used to
    live on this page (chips, sticky bar, combo, row highlight, grouped
    controls) must be gone -- no leftover section ids, no orphaned
    `.lt-*`-prefixed CSS, no dangling references in either file."""
    from webapp import app
    body = app.landing_testing(_Req()).body.decode()
    for demo_id in ("lt-demo-chips", "lt-demo-sticky", "lt-demo-combo",
                    "lt-demo-highlight", "lt-demo-grouped"):
        assert f'id="{demo_id}"' not in body
    assert "Player Comparison layout ideas" not in body
    assert "/playercompare/data" not in body
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert ".lt-" not in css


def test_landing_testing_page_is_a_minimal_placeholder():
    """The page keeps its header/intro (a general "prototypes under review"
    page, same pattern as the loaded-dashboard Testing tab) so future
    prototypes have somewhere to go, but currently holds no content beyond
    that -- an empty page here is the expected state, not a bug."""
    from webapp import app
    body = app.landing_testing(_Req()).body.decode()
    assert "<h2>Testing</h2>" in body
    assert "This page needs no league" in body
    assert "Nothing is currently under review" in body


def test_landing_testing_does_not_touch_real_playercompare_template():
    """Regression guard: the real Player Comparison template must carry no
    trace of the removed Testing-tab demo classes."""
    from webapp import app
    real = (app.BASE / "templates" / "_playercompare_compare.html").read_text(encoding="utf-8")
    assert "lt-demo" not in real
    assert "lt-chip" not in real
