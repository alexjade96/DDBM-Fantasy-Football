# Playoffs — running a bracket Sleeper can't

Sleeper can only express *its own* bracket: a fixed `playoff_week_start`, its own
team count, and lineups locked to whatever the app had. When a league runs the
playoff by hand — a different week range, a custom bracket, and starters handed
to the commissioner because the app wouldn't let managers set them — none of
that fits, and Sleeper's stored bracket becomes unreliable.

(For DDBM 2025 it *is* unreliable: in Sleeper's own `winners_bracket`, the team
recorded as losing in round 1 **and** round 2 is also recorded as winning the
`p == 1` championship game. That bracket is not a coherent elimination tree.)

This engine takes the bracket as **config** and needs only **roster inputs** per
elimination matchup. Everything else — points, winners, advancement — is computed.

## How points are computed

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

## Workflow

```bash
# 1. scaffold a bracket (seeds from standings; pre-fills starters as a baseline)
python playoffs/scaffold.py custom <league_id> playoffs/2025.json \
    --weeks 14 15 16 17 18 --teams 8

# 2. edit playoffs/2025.json: replace each side's `starters` with the lineup
#    actually submitted to the commissioner. Ids or player names both work.

# 3. score it
```

```r
pkgload::load_all("R/sleepermetrics")
p <- sl_playoff("playoffs/2025.json")
p$champion
sl_playoff_summary(p)
sl_plot_playoff_bracket(p)
sl_plot_playoff_matchup(p, "R1M1")   # the receipts: both lineups, player by player
```

```python
import sleepermetrics as sm
p = sm.playoff("playoffs/2025.json")
sm.playoff_summary(p)
```

Or watch it live in the dashboard — the **Playoffs** tab renders the bracket,
per-matchup breakdowns and the stored scoring chart, and re-scores from current
stats on every refresh:

```r
sl_dashboard(playoffs = "playoffs", port = 8100)
```

## Config schema

```jsonc
{
  "season": "2025",
  "league_id": "1252770181306929152",
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
- **`final`** must name the title game — a last round can also hold consolation
  and placement games, so "last matchup" is not a safe assumption.
- **`bye`** passes a team through unscored.
- A matchup whose teams aren't decided yet, or whose lineups haven't been handed
  in, is reported as **`PENDING`** rather than scored as 0–0 — that's what makes
  the bracket safe to run live, week by week, as rounds resolve.
- Submitted lineups are checked against the league's starting slots; anything
  short, over, or flex-illegal is warned about (`sl_check_lineup()`).

## Files

Every season has a stored bracket, holding the **finalized lineups** each team
started. The dashboard's Playoffs tab follows the season picker and loads the
matching one automatically.

| File | Season | Bracket | Champion |
|---|---|---|---|
| `2022.json` | 2022 (6 teams) | standard Sleeper | sparky1335 |
| `2023.json` | 2023 (8 teams) | standard Sleeper | rezzu |
| `2024.json` | 2024 (6 teams) | standard Sleeper | SearingShadow |
| `2025.json` | 2025 (10 teams) | **custom** choose-your-opponent, wks 15–18 | LuckyHarm |
| `fixtures/2025-sleeper-bracket.json` | — | Sleeper's own 2025 bracket, replayed — the engine's ground-truth fixture | — |
| `scaffold.py` | — | generates any of the above from the league | — |

For 2022–2024 the engine reproduces **Sleeper's own recorded champion** from the
stored lineups, which is the check that the scoring is right.

### 2025 is deliberately different

2025's playoff was run by hand, so its bracket comes from config, not the API:

- **Seeding is the regular season (through wk14)** — *not* the final standings,
  which are polluted by the playoff weeks themselves. This is the subtle bit: it
  makes SearingShadow the 3-seed (not the 5-seed), so they took an R1 bye and
  *picked* xPsyD. Seed off the wrong table and the bracket cannot be made to
  resolve at all.
- Seeds 5–8 play R1; seeds 3–4 then **pick** from the R1 winners; seeds 1–2 pick
  from the R2 winners; then the final. Seeds 1 and 2 therefore get **two byes**.
- All 7 games reproduce the known outcomes from the recorded lineups.

Note Sleeper's *own* stored 2025 bracket disagrees (it crowns SimonSmith) — but
that bracket is incoherent: the team it records as losing rounds 1 **and** 2 is
also its `p == 1` champion. The config is the accurate record.
