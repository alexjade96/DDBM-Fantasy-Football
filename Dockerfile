# Python web dashboard (FastAPI + HTMX). Builds from the repo root, because the
# app reads the bracket configs in data/seasons/ and the ADP/stats/nflverse
# caches in data/sources/.
#
#   docker build -t sleepermetrics .
#   docker run -p 8000:8000 sleepermetrics
#
# Deploys as-is to a Render free web service. Also works on Hugging Face Spaces;
# any host that injects $PORT, which the CMD honours.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    PORT=8000

WORKDIR /app

COPY fantasy-football-4-fun/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# repo_paths.py (the shared path-resolution helper), the metrics package, and
# the web layer -- which carries its own cross-platform ADP layer
# (landing-page ADP compare) and nflverse-derived data layer under
# webapp/sources/ -- plus two separate data roots: data/seasons/ (the custom
# playoff bracket configs the Playoffs tab reads, league-scoped) and
# data/sources/ (the ADP/weekly-stats/nflverse caches + default scoring
# chart, source-scoped, not league-scoped -- see data/sources/README.md).
COPY fantasy-football-4-fun/repo_paths.py ./repo_paths.py
COPY fantasy-football-4-fun/sleepermetrics ./sleepermetrics
COPY fantasy-football-4-fun/webapp ./webapp
COPY data/seasons ./data/seasons
COPY data/sources ./data/sources

ENV SLEEPERMETRICS_SEASON_DIR=/app/data/seasons
ENV SLEEPERMETRICS_SOURCES_DIR=/app/data/sources

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

# $PORT is set by the host; default 8000 locally.
CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT}"]
