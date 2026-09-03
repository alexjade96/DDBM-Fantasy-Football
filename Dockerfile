# Python web dashboard (FastAPI + HTMX). Builds from the repo root, because the
# app reads the bracket configs and ADP cache in season/.
#
#   docker build -t sleepermetrics .
#   docker run -p 8000:8000 sleepermetrics
#
# Deploys as-is to a Render free web service (see docs/hosting-cicd-plan.md).
# Also works on Hugging Face Spaces; any host that injects $PORT, which the CMD
# honours.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    PORT=8000

WORKDIR /app

COPY python/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The package, the web layer, and the season data (bracket configs the
# Playoffs tab reads, plus the ADP cache the Draft tab's redraft report reads).
COPY python/sleepermetrics ./sleepermetrics
COPY python/webapp ./webapp
COPY season ./season

ENV SLEEPERMETRICS_SEASON_DIR=/app/season

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

# $PORT is set by the host; default 8000 locally.
CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT}"]
