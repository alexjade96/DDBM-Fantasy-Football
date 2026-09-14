# data/seasons/: playoff brackets Sleeper can't run

This directory is the one durable-data location for the custom playoff
engine's bracket configs, one subfolder per league (keyed by its chain's
root id -- see below), every season it's ever played under. It holds ONLY
league-scoped data. Everything else that used to live alongside it here
(the Sleeper ADP cache, weekly stat caches, nflverse snapshots, the default
scoring chart) is organized by SOURCE first, season only as a leaf -- see
the sibling directory `data/sources/README.md`.

The brackets are plain checked-in JSON read by both the R and Python
engines.

```
data/seasons/
  <root_league_id>/<season>_season.json   # one subfolder per REAL league
                                    # (its chain's oldest/root id, see below),
                                    # every season it's ever played under.
                                    # The filename MUST be exactly
                                    # <season>_season.json -- that's the only
                                    # pattern config_paths()/sl_playoff_configs()
                                    # treat as the authoritative bracket for
                                    # a season (see "Config filename
                                    # convention" below)
  <root_league_id>/<season>_bracket.json  # OPTIONAL: a reference file for
                                    # that same season -- e.g. a replay of
                                    # Sleeper's own (possibly incoherent)
                                    # stored bracket, kept only as a
                                    # ground-truth comparison. Ignored by
                                    # config_paths() -- never returned as
                                    # "the" bracket for that season
  scaffold.py                      # generates a bracket config for the
                                    # workflow below; prints the root id
```

## Playoff brackets

Sleeper can only express *its own* bracket: a fixed `playoff_week_start`, its own
team count, and lineups locked to whatever the app had. When a league runs the
playoff by hand (a different week range, a custom bracket, and starters handed
to the commissioner because the app wouldn't let managers set them), none of
that fits, and Sleeper's stored bracket becomes unreliable.

(For DDBM 2025 it *is* unreliable: in Sleeper's own `winners_bracket`, the team
recorded as losing in round 1 **and** round 2 is also recorded as winning the
`p == 1` championship game. That bracket is not a coherent elimination tree.)

This engine takes the bracket as **config** and needs only **roster inputs** per
elimination matchup. Everything else (points, winners, advancement) is computed.

### Why one subfolder per league, keyed by the chain's ROOT id

A bracket config is keyed by season, but a season *number* is not unique across
leagues, and Sleeper gives every season of a league its own, DIFFERENT league
id (a new league object each year, chained backwards via `previous_league_id`),
so even DDBM's own history has a different league id every season. Naively
keying the folder by each season's own id would scatter one real league's
brackets across as many folders as it has seasons, exactly the opposite of
"grouped by league."

Instead the folder key is the chain's **root** (oldest) league_id.
`sl_root_league_id()` / `root_league_id()` walks `previous_league_id` all the
way back to the season with none, which never changes: new seasons only ever
extend the chain forward, so today's root is next year's root too. For DDBM
that's 2022's own id (`870378308704141312`, its earliest tracked season), so
its whole history lives under `data/seasons/870378308704141312/`. Each file's own
`league_id` field still holds THAT season's real, individual id (needed for
`config_paths()`'s league-filtering, and for `sl_playoff()`/`sm.playoff()` to
fetch that season's own data); only the surrounding folder is grouped by root.

`config_paths()`/`sl_playoff_configs()` walk `data/seasons/<root_league_id>/*_season.json`,
filtering to only numeric-named subfolders (`data/sources/` is a sibling of
`data/seasons/` entirely, not a subfolder under it, so it's never even a glob
candidate). `data/seasons/scaffold.py` prints the resolved root id after
writing a config, so a brand-new season lands in the right existing folder
instead of a fresh one.

### Config filename convention

The filename must be **exactly `<season>_season.json`** to be treated as the
authoritative bracket for that season -- `config_paths()`/`sl_playoff_configs()`
match that pattern specifically, not just any `.json` in the folder.

A league folder can also hold OTHER files for the same season -- most
commonly a Sleeper-bracket replay kept only as a ground-truth check (DDBM's
`870378308704141312/2025_bracket.json`, `league_id: 1252770181306929152`,
the same real league, replayed through Sleeper's own stored bracket instead
of the custom one). Any name that doesn't match `<season>_season.json` is
simply ignored by the lookup, rather than racing the real config for the
same season key.

This matters because the two files can legitimately claim the SAME season
(`"season": "2025"` in both) -- before this filename filter existed, ANY
`.json` in a league folder was accepted and keyed by its own internal
`season` field, so two same-season files would silently collide (whichever
sorted last alphabetically won). Keep this convention when scaffolding a new
config or adding a reference file: only ever name the real, authoritative
bracket `<season>_season.json`.

### How points are computed

Not read from Sleeper's matchup rows (they only know the lineup Sleeper had).
Instead each submitted starter is priced from raw NFL stat lines under the
league's own **point-calculation chart** (`scoring_settings`):

```
points = Σ (stat × league weight)
```

This is verified faithful: replaying Sleeper's own 2025 bracket through the
engine reproduced **all 12 of its matchup winners and the champion, with zero
mismatches**, and the per-player scoring matched Sleeper's own numbers on
175/175 players in week 15.

The chart is **snapshotted into the config**, so a finished bracket keeps scoring
the same even if league settings change later.

Sleeper keys the chart by internal stat code (`pass_yd`, `bonus_rec_te`,
`pts_allow_7_13`), which is fine for arithmetic and unreadable to a human. Both
dashboards therefore render it through `sl_scoring_readable()` /
`sm.scoring_readable()`, which groups the rules and states each one in plain
English: `pass_yd: 0.04` becomes **Passing yards, 1 point per 25 yards**, while
still showing the raw code beside it. Unknown keys are never dropped; they land in
an "Other" group under their raw name, so a new Sleeper stat shows up rather than
silently vanishing from the chart the season was decided by.

### Workflow

```bash
# 1. scaffold a bracket (seeds from standings; pre-fills starters as a baseline)
#    -- prints the root league id to use as the folder; DDBM's is
#    870378308704141312, so its 2025 bracket goes under that folder, not
#    under 2025's own (different) league_id. The output filename must be
#    <season>_season.json to be recognized as the authoritative config.
python data/seasons/scaffold.py custom <league_id> data/seasons/870378308704141312/2025_season.json \
    --weeks 14 15 16 17 18 --teams 8

# 2. edit data/seasons/870378308704141312/2025_season.json: replace each side's
#    `starters` with the lineup actually submitted to the commissioner. Ids or
#    player names both work.

# 3. score it
```

```r
pkgload::load_all("r-analysis/sleepermetrics")
p <- sl_playoff("data/seasons/870378308704141312/2025_season.json")
p$champion
sl_playoff_summary(p)
sl_plot_playoff_bracket(p)
sl_plot_playoff_matchup(p, "R1M1")   # the receipts: both lineups, player by player
```

```python
import sleepermetrics as sm
p = sm.playoff("data/seasons/870378308704141312/2025_season.json")
sm.playoff_summary(p)
```

Or watch it live in the dashboard: the **Playoffs** tab renders the bracket,
per-matchup breakdowns and the stored scoring chart, and re-scores from current
stats on every refresh:

```r
sl_dashboard(playoffs = sl_season_dir(), port = 8100)
```

### Config schema

```jsonc
{
  "season": "2025",
  "league_id": "1252770181306929152",   // THIS season's own real id -- NOT
                                         // the folder's root id (see above)
  "roster_positions": ["QB","RB","RB","WR","WR","TE","FLEX","K","DEF","BN", ...],
  "scoring_settings": { "pass_td": 4.0, "rec": 1.0, ... },   // snapshot; 48 rules
  "final": "R3M1",                    // which matchup is the TITLE game
  "rounds": [
    {
      "id": "R1", "name": "Round 1",
      "weeks": [14],                  // several weeks = one cumulative round
      "matchups": [
        { "id": "R1M1",
          "home": { "team": "LuckyHarm", "starters": ["4034", "Bijan Robinson", "SEA"] },
          "away": { "team": "xPsyD",     "starters": [...] } },
        { "id": "R1M2", "bye": "SimonSmith" }
      ]
    },
    {
      "id": "R2", "name": "Final", "weeks": [16],
      "matchups": [
        { "id": "R2M1",
          "home": { "team": "W:R1M1", "starters": [...] },   // winner of R1M1
          "away": { "team": "W:R1M2", "starters": [...] } }
      ]
    }
  ]
}
```

Notes:

- **`starters`** accept player ids *or* player names (`"SEA"` for a defense).
  They are the only thing you must supply.
- **`W:<matchup_id>`** / **`L:<matchup_id>`** advance winners/losers automatically,
  so later rounds wire themselves up. `L:` lets you build a consolation bracket.
- **`weeks`** with more than one entry makes a cumulative multi-week round.
- **`final`** must name the title game; a last round can also hold consolation
  and placement games, so "last matchup" is not a safe assumption.
- **`bye`** passes a team through unscored.
- A matchup whose teams aren't decided yet, or whose lineups haven't been handed
  in, is reported as **`PENDING`** rather than scored as 0–0, which is what makes
  the bracket safe to run live, week by week, as rounds resolve.
- Submitted lineups are checked against the league's starting slots; anything
  short, over, or flex-illegal is warned about (`sl_check_lineup()`).

### Files

Every season has a stored bracket, holding the **finalized lineups** each team
started. The dashboard's Playoffs tab follows the season picker and loads the
matching one automatically.

All four live under the same root folder, `870378308704141312/` (DDBM's 2022
id, its chain's origin); the "season's own league_id" column below is each
year's genuinely different real id, still stored inside that file's own
`league_id` field: the exact mismatch `sl_root_league_id()` exists to paper
over at the folder level.

| File | Season's own league_id | Season | Bracket | Champion |
|---|---|---|---|---|
| `870378308704141312/2022_season.json` | 870378308704141312 | 2022 (6 teams) | standard Sleeper | sparky1335 |
| `870378308704141312/2023_season.json` | 1003483425623355392 | 2023 (8 teams) | standard Sleeper | rezzu |
| `870378308704141312/2024_season.json` | 1107490594215063552 | 2024 (6 teams) | standard Sleeper | SearingShadow |
| `870378308704141312/2025_season.json` | 1252770181306929152 | 2025 (10 teams) | **custom** choose-your-opponent, wks 15–18 | LuckyHarm |
| `870378308704141312/2025_bracket.json` | 1252770181306929152 | 2025 | Sleeper's own 2025 bracket, replayed; the engine's ground-truth fixture (same real league, not "the" config -- see filename convention above) | - |
| `scaffold.py` | - | - | generates any of the above from the league | - |

For 2022–2024 the engine reproduces **Sleeper's own recorded champion** from the
stored lineups, which is the check that the scoring is right.

#### 2025 is deliberately different

2025's playoff was run by hand, so its bracket comes from config, not the API:

- **Seeding is the regular season (through wk14)**, *not* the final standings,
  which are polluted by the playoff weeks themselves. This is the subtle bit: it
  makes SearingShadow the 3-seed (not the 5-seed), so they took an R1 bye and
  *picked* xPsyD. Seed off the wrong table and the bracket cannot be made to
  resolve at all.
- Seeds 5–8 play R1; seeds 3–4 then **pick** from the R1 winners; seeds 1–2 pick
  from the R2 winners; then the final. Seeds 1 and 2 therefore get **two byes**.
- All 7 games reproduce the known outcomes from the recorded lineups.

Note Sleeper's *own* stored 2025 bracket disagrees (it crowns SimonSmith), but
that bracket is incoherent: the team it records as losing rounds 1 **and** 2 is
also its `p == 1` champion. The config is the accurate record.

## Location override

Resolved from the environment variable `SLEEPERMETRICS_SEASON_DIR` (default:
`data/seasons/` under the repo root), set by `launch.py`, the `Dockerfile`,
and `repo_paths.py`'s own fallback alike (`sl_season_dir()` on the R side).
This is a SEPARATE env var and constant from `SLEEPERMETRICS_SOURCES_DIR`/
`SOURCES_DIR` (see `data/sources/README.md`), which governs the ADP/stats/
nflverse/scoring caches -- the two roots are deliberately independent, since
one is organized by league+season and the other by source+season.
