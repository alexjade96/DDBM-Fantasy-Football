# Sentiment Analysis (news pipeline) -- planning & benchmarking

## What this is

A standalone, **pre-decision** subproject for a planned feature: a continually
updating news-sentiment pipeline for NFL players/teams, split by team/player
in a future webapp News tab, that ranks incoming source material by how
positive/negative it is for a player's fantasy value and builds a historical
record of source reliability over time.

This directory does **not** touch `fantasy-football-4-fun/sleepermetrics`,
`fantasy-football-4-fun/webapp`, or `CLAUDE.md`'s parity-checked metric
contract. It is deliberately isolated
so research/benchmarking work can proceed without any risk to the production
webapp. Nothing here is wired into the live site yet.

## Status: benchmarking phase

No model, source list, or hosting venue has been chosen yet. Before building
a real pipeline, this directory exists to answer one question with actual
numbers instead of vendor claims: **which sentiment model, if any, correctly
classifies real NFL news/injury text as good/bad/neutral for fantasy value?**

See `benchmark/` below.

## Why a separate directory (not inside `fantasy-football-4-fun/`)

- `fantasy-football-4-fun/requirements.txt` backs the live Render-hosted webapp on a 512MB
  free-tier instance with no persistent disk. Adding `torch`/`transformers`
  there risks breaking that deployment before any of this is proven useful.
- This subproject may end up running somewhere else entirely (a GitHub
  Actions cron job, a separate cloud service) rather than inside the webapp
  process -- see "Architecture notes" below. Keeping it structurally separate
  avoids assuming the answer before the research is done.
- Nothing here is parity-checked against an R implementation the way
  `sleepermetrics` is; it has no R counterpart and isn't expected to get one.

## Layout

```
sentiment-analysis/
  README.md              -- this file
  requirements.txt       -- benchmarking deps (transformers, torch-cpu, vaderSentiment, datasets, scikit-learn)
  benchmark/              -- code only, owns no data of its own
    __init__.py
    models.py             -- thin common interface over each candidate model
    loader.py             -- loads the HF football_news dataset + Data/hand-labeled/, in a common shape
    run.py                -- CLI: scores every dataset with every available model, prints metrics
  Data/                   -- all data lives here, so benchmark/ (and any later
                             pipeline code) has one shared place to read from
    hand-labeled/
      hand_labeled.csv    -- real NFL news text, hand-labeled (fill this in). Tracked in git -- small,
                             hand-authored, same convention as data/seasons/adp/'s committed snapshots.
    beat-writers/          -- reserved for scraped beat-writer content once a real source is wired up.
                             Empty for now (gitignored except .gitkeep); not read by anything yet.
    news-feeds/             -- reserved for scraped RSS/news-API pulls. Same status as beat-writers/.
  Models/                 -- reserved for downloaded model weights/checkpoints, if ever cached to
                             disk instead of pulled fresh from Hugging Face each run. Empty for now
                             (gitignored except .gitkeep); benchmark/models.py currently downloads
                             straight from the Hugging Face Hub and does not read from here.
```

## Running the benchmark

```
cd sentiment-analysis
python -m venv venv
venv\Scripts\activate        # Windows PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m benchmark.run
```

First run downloads model weights from Hugging Face (a few hundred MB) and
the `james-kramer/football_news` dataset -- both cached locally after that.
No network access is required for VADER.

## Models under comparison (see `benchmark/models.py`)

| Model | Why it's here | Why it might not win |
|---|---|---|
| `cardiffnlp/twitter-roberta-base-sentiment-latest` | Well-maintained general sentiment model, handles informal/short text | Not sports- or finance-tuned; tone-based, not value-based |
| `ProsusAI/finbert` | Financial news sentiment is structurally similar to "is this good/bad for value" -- the same restrained-but-consequential register as injury/beat-writer text | Trained on financial text, not sports vocabulary |
| VADER (`vaderSentiment`) | Zero download, zero inference cost, instant baseline | Lexicon-based; no understanding of football-specific negative signals ("questionable," "ruled out," "limited practice") |

`NeuML/sportsbert-small` and `AventIQ-AI/sentiment-analysis-for-sports-fan-sentiment`
were researched but **excluded from this benchmark round**:
- `sportsbert-small` is a base encoder (sports-domain pretraining only) with
  no classification head -- it can't produce a sentiment label out of the box
  and would need a labeled fine-tuning run first, which depends on this
  benchmark's own hand-labeled data existing in enough volume.
- The AventIQ sports-fan-sentiment model reads *fan/crowd mood*, which is a
  different signal than *is this news good or bad for the player's value*.
  Worth a follow-up test once there's a labeled sample to check it against,
  but not assumed to transfer.
- `microsoft/SportsBERT` could not be verified to exist on Hugging Face under
  that name during research -- treat any reference to it as unconfirmed.

## Datasets used

- `james-kramer/football_news` (Hugging Face) -- binary positive/negative
  football news sentiment, stratified 80/10/10 splits. The only
  purpose-built benchmark dataset found during research; general football
  news, not NFL-fantasy-specific.
- `Data/hand-labeled/hand_labeled.csv` -- a small starter set of real NFL
  injury/beat-writer style text, hand-labeled by domain judgment (does this
  read as good/bad/neutral for the player's fantasy value). This is the more
  important of the two datasets for this feature's actual use case, since no
  public dataset targets "NFL fantasy news sentiment" directly. **Needs to be
  grown** -- the starter rows are just a format example, not a real sample
  size. Labeling more real examples here is the single highest-value next
  step before picking a model.

## Architecture notes (not yet decided/built)

Full research is in the conversation that produced this directory; summary
for whoever picks this up next:

- **Hosting constraint**: the production webapp (`fantasy-football-4-fun/webapp`) deploys to
  Render's free tier -- 512MB RAM, no persistent disk, sleeps after 15min
  idle. A continually-updating scraper + model can't live inside that
  process. Leading candidate: a scheduled GitHub Actions workflow (same
  pattern as the documented-but-not-yet-built `weekly-recap.yml`) that
  scrapes, scores, and commits snapshots to `data/seasons/news/` the same way
  `data/seasons/adp/` already works -- $0 cost, no new hosting account, matches
  every existing convention in this repo. A second-tier option (if data
  volume outgrows flat JSON files committed to git) is Google Cloud Run +
  Cloud Storage, which has a genuinely free tier unlike Fly.io (which now
  requires a credit card and bills persistent volumes even while sleeping).
- **Source candidates researched**: nflverse (`load_injuries`,
  `load_depth_charts`, `load_snap_counts` -- structured status data, not
  prose), RSS feeds (RotoWire, team SB Nation blogs, NFL.com -- legitimate
  syndication, lowest legal risk for scraping prose), ESPN's undocumented
  news/injuries JSON endpoints (same unofficial-endpoint pattern already
  used in `fantasy-football-4-fun/webapp/sources/ffadp/espn.py`), GNews.io/Currents API (general news APIs
  with sports category filters). Reddit and Twitter/X were researched and
  ruled out for now -- Reddit's ToS effectively requires a registered OAuth
  app for scheduled polling, and Twitter/X scraping (via Nitter or similar)
  is a dead end after Nitter's August 2026 shutdown.
- **Existing conventions to mirror** once a real pipeline is built: the
  fetch -> validate -> in-process cache -> disk snapshot -> live-fallback
  pattern already used three times in this repo (`fantasy-football-4-fun/webapp/sources/ffadp/{api,cache}.py`,
  `fantasy-football-4-fun/webapp/sources/nflref/`, `fantasy-football-4-fun/sleepermetrics/api.py`). A production module
  would likely be `fantasy-football-4-fun/newssentiment/{api.py, cache.py, score.py, board.py}`
  with snapshots under `data/seasons/news/<source>/<year>.json`, following
  `fantasy-football-4-fun/webapp/sources/ffadp/base.py`'s ABC-provider-contract pattern.
- **`Data/beat-writers/` and `Data/news-feeds/`** are placeholders for that
  future ingestion, kept here (not yet under `data/seasons/`) because nothing reads
  or writes them yet and this whole directory is pre-decision. If/when a real
  scraper is built, decide then whether its output stays here permanently or
  migrates to `data/seasons/news/...` alongside the rest of the repo's committed
  snapshots -- don't assume this location is final.

None of this is committed to yet -- it's the shape the research pointed
toward, recorded here so it isn't re-derived from scratch later.
