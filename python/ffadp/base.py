"""The provider contract every ADP source implements."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

# Scoring formats the board understands. A source that only publishes one
# format maps every request onto it (and says so via `formats`).
SCORING = ("std", "half_ppr", "ppr", "2qb")

# How ADP sources are grouped in the comparison table, in display order.
# `apps` are the mainstream draft apps most people actually draft on;
# `highstakes` are the high-stakes / best-ball contest platforms (their
# published ADP is a cross-league aggregate); `analyst` is compiled /
# consensus ADP with no first-party draft app behind it. The board orders
# its columns by this grouping and returns the groups so the UI can label
# and filter by them.
GROUPS = (
    ("apps", "Draft apps"),
    ("highstakes", "High-stakes & best-ball"),
    ("analyst", "Analyst consensus"),
)
GROUP_ORDER = {key: i for i, (key, _) in enumerate(GROUPS)}
GROUP_LABEL = dict(GROUPS)


@dataclass
class AdpRow:
    """One player's ADP from one source, before cross-source keying.

    `sleeper_id` is filled by identity.resolve() when the source carries an
    espn/yahoo id or a confident name+position match; until then it may be
    None and the row still merges on (name, position) as a fallback.
    `adp` is the value for the requested scoring format (a source that only
    has one format returns that). `overall_rank` is 1-based within the
    source's own list, filled by the provider or by the board.
    """
    source: str
    name: str
    position: str | None = None
    team: str | None = None
    adp: float | None = None
    overall_rank: int | None = None
    sleeper_id: str | None = None
    espn_id: str | None = None
    yahoo_id: str | None = None
    extra: dict = field(default_factory=dict)


class AdpProvider(abc.ABC):
    """A single platform's season-wide, REDRAFT ADP.

    Contract for a new source:
      * `name`   -- short lowercase id ("sleeper", "espn"). Also the snapshot
                    subdir under season/adp/<name>/.
      * `label`  -- column header text ("Sleeper", "ESPN").
      * `formats`-- the SCORING keys this source can actually distinguish; the
                    board falls back to `formats[0]` for an unsupported ask.
                    A source that publishes one ADP lists all four (it stands
                    in for every mode).
      * module-level `EARLIEST` -- the oldest year the source has real ADP for
                    (None = no public history). ffadp.board reads it for the
                    coverage notes + the season-picker lower bound.
      * `fetch(season, scoring, reload=False)` -- snapshot-first (via
                    ffadp.cache), live only when the snapshot is missing or
                    `reload`. Must DEGRADE to [] rather than raise when the
                    upstream is unavailable; must never require credentials;
                    REDRAFT data only (not dynasty / rookie / IDP).
      * each row carries a cross-platform id (espn_id / yahoo_id) OR a clean
                    name+position so ffadp.identity.resolve() can key it onto
                    the canonical Sleeper player_id.
    """

    #: short lowercase id, e.g. "sleeper" / "espn". Also the snapshot subdir.
    name: str = ""
    #: human label for the column header.
    label: str = ""
    #: which SCORING formats this source can actually distinguish; the board
    #: falls back to the source's first listed format for an unsupported ask.
    formats: tuple[str, ...] = SCORING
    #: which GROUPS bucket this source belongs to ("apps" / "highstakes" /
    #: "analyst"); the board orders columns by this and reports the groups.
    group: str = "analyst"

    @abc.abstractmethod
    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        """This source's ADP rows for the season. Snapshot-first; `reload`
        forces a live re-fetch that rewrites the snapshot. Returns [] when
        nothing resolves."""
        raise NotImplementedError

    def _format_or_fallback(self, scoring: str) -> str:
        return scoring if scoring in self.formats else self.formats[0]
