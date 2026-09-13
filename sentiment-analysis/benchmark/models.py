"""Thin common interface over each candidate sentiment model.

Every model exposes `predict(text) -> "positive" | "negative" | "neutral"`,
normalised to that 3-way label set regardless of the underlying model's own
label names, so run.py can score every candidate against the same datasets
without per-model branching.

sportsbert-small and the AventIQ sports-fan-sentiment model are deliberately
NOT included here yet -- see README.md's "Models under comparison" table for
why. Add them once there's a reason to believe they'd help (a fine-tuning
dataset for the former, a labeled comparison showing fan-mood transfers to
fantasy-value sentiment for the latter).
"""
from __future__ import annotations

import abc


class SentimentModel(abc.ABC):
    """Contract for a benchmark candidate.

    `key`   -- short id used in result tables / CLI --models filtering.
    `label` -- human-readable name for report output.
    `load()` is called once before any `predict()` calls; heavy model/tokenizer
    downloads happen there, not at import time, so `run.py` can list available
    models without paying the download cost for ones the user excludes.
    """

    key: str = ""
    label: str = ""

    @abc.abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def predict(self, text: str) -> str:
        """Return one of "positive", "negative", "neutral"."""
        raise NotImplementedError


class VaderModel(SentimentModel):
    """Lexicon/rule-based baseline. No download, no torch, always available."""

    key, label = "vader", "VADER (lexicon baseline)"

    def __init__(self) -> None:
        self._analyzer = None

    def load(self) -> None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        self._analyzer = SentimentIntensityAnalyzer()

    def predict(self, text: str) -> str:
        compound = self._analyzer.polarity_scores(text)["compound"]
        # Thresholds are VADER's own documented convention, not tuned here.
        if compound >= 0.05:
            return "positive"
        if compound <= -0.05:
            return "negative"
        return "neutral"


class _HFPipelineModel(SentimentModel):
    """Shared plumbing for a Hugging Face `text-classification` pipeline.

    Subclasses supply `model_id` and a `_LABEL_MAP` from the model's own
    output labels to the normalised 3-way set this harness compares on.
    """

    model_id: str = ""
    _LABEL_MAP: dict[str, str] = {}

    def __init__(self) -> None:
        self._pipe = None

    def load(self) -> None:
        from transformers import pipeline
        self._pipe = pipeline(
            "text-classification", model=self.model_id, top_k=None,
        )

    def predict(self, text: str) -> str:
        # top_k=None returns every class's score; take the highest.
        scores = self._pipe(text[:512])[0]
        best = max(scores, key=lambda s: s["score"])
        return self._LABEL_MAP.get(best["label"], best["label"].lower())


class CardiffRobertaModel(_HFPipelineModel):
    """General-purpose sentiment, trained on informal short text (tweets)."""

    key, label = "cardiffnlp", "cardiffnlp/twitter-roberta-base-sentiment-latest"
    model_id = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    # This model's own labels: LABEL_0=negative, LABEL_1=neutral, LABEL_2=positive.
    _LABEL_MAP = {
        "LABEL_0": "negative", "LABEL_1": "neutral", "LABEL_2": "positive",
        "negative": "negative", "neutral": "neutral", "positive": "positive",
    }


class FinBertModel(_HFPipelineModel):
    """Financial-news sentiment -- included because "is this good/bad for
    value" is structurally closer to financial sentiment than to general
    tone or fan-mood sentiment. See README.md."""

    key, label = "finbert", "ProsusAI/finbert"
    model_id = "ProsusAI/finbert"
    _LABEL_MAP = {"positive": "positive", "negative": "negative", "neutral": "neutral"}


# Registry, in the order they should be listed/run by default.
MODELS: dict[str, type[SentimentModel]] = {
    m.key: m for m in (VaderModel, CardiffRobertaModel, FinBertModel)
}


def available_models() -> list[str]:
    return list(MODELS.keys())


def build(key: str) -> SentimentModel:
    try:
        cls = MODELS[key]
    except KeyError:
        raise ValueError(
            f"Unknown model {key!r}. Available: {', '.join(available_models())}"
        ) from None
    return cls()
