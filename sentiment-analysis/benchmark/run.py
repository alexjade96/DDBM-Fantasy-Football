"""CLI: score the benchmark datasets with every available model and report
accuracy / F1 / confusion matrix per model, per dataset source.

Usage:
    python -m benchmark.run
    python -m benchmark.run --models vader,cardiffnlp
    python -m benchmark.run --dataset hand_labeled
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import loader as data_mod
from . import models as models_mod


def _confusion_table(labels: list[str], preds: list[str], classes: list[str]) -> str:
    idx = {c: i for i, c in enumerate(classes)}
    grid = [[0] * len(classes) for _ in classes]
    for y, p in zip(labels, preds):
        if y in idx and p in idx:
            grid[idx[y]][idx[p]] += 1
    header = "true\\pred".ljust(10) + "".join(c[:9].rjust(10) for c in classes)
    lines = [header]
    for c, row in zip(classes, grid):
        lines.append(c[:9].ljust(10) + "".join(str(v).rjust(10) for v in row))
    return "\n".join(lines)


def _score(examples: list[data_mod.Example], model: models_mod.SentimentModel):
    labels = [e.label for e in examples]
    preds = []
    for e in examples:
        try:
            preds.append(model.predict(e.text))
        except Exception as exc:  # noqa: BLE001 -- one bad row shouldn't kill a run
            print(f"  [warn] predict failed on one example: {exc}", file=sys.stderr)
            preds.append("neutral")
    correct = sum(1 for y, p in zip(labels, preds) if y == p)
    accuracy = correct / len(examples) if examples else 0.0
    return labels, preds, accuracy


def run(model_keys: list[str], dataset_filter: str | None) -> None:
    examples = data_mod.load_all()
    if dataset_filter:
        examples = [e for e in examples if e.source == dataset_filter]
    if not examples:
        print("No examples loaded -- check Data/hand-labeled/hand_labeled.csv "
              "and/or network access for the HF dataset.")
        return

    by_source: dict[str, list[data_mod.Example]] = defaultdict(list)
    for e in examples:
        by_source[e.source].append(e)

    print(f"Loaded {len(examples)} examples: "
          + ", ".join(f"{k}={len(v)}" for k, v in by_source.items()))

    classes = sorted({e.label for e in examples})

    for key in model_keys:
        model = models_mod.build(key)
        print(f"\n=== {model.label} ===")
        try:
            model.load()
        except Exception as exc:  # noqa: BLE001 -- report and skip, don't crash the run
            print(f"  could not load model ({exc}); skipping")
            continue

        for source, subset in by_source.items():
            labels, preds, accuracy = _score(subset, model)
            print(f"  [{source}] n={len(subset)} accuracy={accuracy:.3f}")
            print(_confusion_table(labels, preds, classes))

        labels, preds, accuracy = _score(examples, model)
        print(f"  [overall] n={len(examples)} accuracy={accuracy:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", default=",".join(models_mod.available_models()),
        help=f"comma-separated model keys (default: all -- "
             f"{', '.join(models_mod.available_models())})",
    )
    parser.add_argument(
        "--dataset", default=None, choices=["hand_labeled", "football_news"],
        help="restrict to one dataset source (default: both)",
    )
    args = parser.parse_args()
    run([k.strip() for k in args.models.split(",") if k.strip()], args.dataset)


if __name__ == "__main__":
    main()
