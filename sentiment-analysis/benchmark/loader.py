"""Loads benchmark datasets into a common (text, label) shape.

benchmark/ is standalone code -- it owns no data of its own. Everything it
reads lives in ../Data/ (the shared home for hand-labeled examples, and
later, scraped beat-writer/news-feed content the real pipeline collects), so
this module is the one place that link between code and data is made.

Labels are normalised to the same "positive"/"negative"/"neutral" set
models.py's predictions use, so run.py can score every dataset identically.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[1] / "Data"
HAND_LABELED_PATH = _DATA_DIR / "hand-labeled" / "hand_labeled.csv"


@dataclass
class Example:
    text: str
    label: str  # "positive" | "negative" | "neutral"
    source: str  # which dataset this came from, for per-source reporting


def load_football_news(split: str = "test") -> list[Example]:
    """james-kramer/football_news from Hugging Face -- binary pos/neg football
    news sentiment. Requires network on first call (datasets library caches
    it locally after that). Returns [] if the dataset can't be reached, so a
    benchmark run degrades to hand_labeled.csv alone rather than crashing.
    """
    try:
        from datasets import load_dataset
        ds = load_dataset("james-kramer/football_news", split=split)
    except Exception as exc:  # noqa: BLE001 -- best-effort, report and continue
        print(f"[data] could not load james-kramer/football_news ({exc}); skipping")
        return []

    out: list[Example] = []
    for row in ds:
        text = row.get("text") or row.get("sentence") or row.get("content")
        label_raw = row.get("label")
        if text is None or label_raw is None:
            continue
        # Dataset card documents 0=negative, 1=positive (binary, no neutral).
        label = "positive" if int(label_raw) == 1 else "negative"
        out.append(Example(text=str(text), label=label, source="football_news"))
    return out


def load_hand_labeled(path: Path = HAND_LABELED_PATH) -> list[Example]:
    """The local starter/growing set of real NFL news text. See README.md --
    this is the more important dataset for the actual use case and is meant
    to be grown well past its current starter-row count before it's used to
    make a real model decision.
    """
    if not path.exists():
        return []
    out: list[Example] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip().lower()
            if not text or label not in {"positive", "negative", "neutral"}:
                continue
            out.append(Example(text=text, label=label, source="hand_labeled"))
    return out


def load_all() -> list[Example]:
    return load_hand_labeled() + load_football_news()
