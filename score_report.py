#!/usr/bin/env python3
"""Report the rarity-score distribution for score model 2 (0-1000).

The point of the score is ordering, so this script measures what the old model
got wrong: how many distinct values exist, and how much of the corpus piles
into a single bucket.

Examples::

    python score_report.py
    python score_report.py --json
    python score_report.py --lists data/word_lists/semi_names.txt --top 10

Default corpus: the built-in tier lists (words_* + firstnames_*), deduplicated
and filtered to legal usernames, which is 50,409 names.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.rarity import class_for_score, score, tier_for_score  # noqa: E402

DEFAULT_LISTS = [
    "words_top.txt",
    "words_og.txt",
    "words_semi_og.txt",
    "firstnames_top.txt",
    "firstnames_og.txt",
    "firstnames_semi_og.txt",
]

EXAMPLES = 5


def _legal(word: str) -> bool:
    return 3 <= len(word) <= 16 and word.isascii() and all(
        c.isalnum() or c == "_" for c in word
    )


def load_corpus(paths: list[Path]) -> list[str]:
    words: set[str] = set()
    for path in paths:
        try:
            handle = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            print(f"! skipping {path}: not found", file=sys.stderr)
            continue
        with handle:
            for line in handle:
                word = line.split("\t")[0].strip().lower()
                if word and _legal(word):
                    words.add(word)
    return sorted(words)


def build_report(words: list[str], top: int = 10) -> dict:
    scores = [score(word) for word in words]
    buckets = Counter(scores)
    classes = Counter()
    class_scores: dict[str, list[int]] = defaultdict(list)
    for word, value in zip(words, scores):
        cls = class_for_score(value)
        classes[cls.label] += 1
        class_scores[cls.label].append(value)

    total = len(scores) or 1
    biggest_score, biggest_count = buckets.most_common(1)[0] if buckets else (0, 0)
    examples = {}
    for value in buckets:
        examples.setdefault(value, [])
    for word, value in zip(words, scores):
        bucket = examples[value]
        if len(bucket) < EXAMPLES:
            bucket.append(word)

    ties = [
        {
            "score": value,
            "count": count,
            "examples": examples[value],
        }
        for value, count in buckets.most_common(top)
    ]
    return {
        "corpus": total,
        "distinct_scores": len(buckets),
        "biggest_bucket": {
            "score": biggest_score,
            "count": biggest_count,
            "share": biggest_count / total,
        },
        "score_range": [min(scores), max(scores)] if scores else [0, 0],
        "tier_counts": dict(
            Counter(tier_for_score(value) for value in scores)
        ),
        "classes": [
            {
                "class": label,
                "base": class_for_score(min(values)).base,
                "count": len(values),
                "share": len(values) / total,
                "min": min(values),
                "max": max(values),
            }
            for label, values in sorted(
                class_scores.items(), key=lambda item: -min(item[1])
            )
        ],
        "top_ties": ties,
    }


def print_report(report: dict):
    print(f"Corpus            : {report['corpus']:,} names")
    print(f"Distinct scores   : {report['distinct_scores']:,}")
    print(f"Score range       : {report['score_range'][0]}-{report['score_range'][1]}")
    biggest = report["biggest_bucket"]
    print(f"Largest bucket    : {biggest['score']} with "
          f"{biggest['count']:,} names ({biggest['share']:.1%})")
    print(f"Tiers             : " + ", ".join(
        f"{k}={v:,}" for k, v in sorted(report["tier_counts"].items())
    ))
    print()
    print(f"{'Class':<28}{'Band':>12}{'Count':>9}{'Share':>8}{'Min':>6}{'Max':>6}")
    print("-" * 69)
    for row in report["classes"]:
        print(f"{row['class']:<28}{str(row['base']):>12}"
              f"{row['count']:>9,}{row['share']:>8.1%}"
              f"{row['min']:>6}{row['max']:>6}")
    print()
    print("Top ties:")
    for row in report["top_ties"]:
        examples = ", ".join(row["examples"])
        print(f"  {row['score']:>4}  {row['count']:>6,} names  ({examples})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lists", nargs="*", default=None,
        help="Extra word-list files to score on top of the built-in corpus",
    )
    parser.add_argument("--top", type=int, default=10,
                        help="How many tie buckets to show (default: 10)")
    parser.add_argument("--json", action="store_true",
                        help="Print the report as JSON")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    paths = [root / "data" / "word_lists" / name for name in DEFAULT_LISTS]
    paths += [Path(p) for p in (args.lists or [])]

    words = load_corpus(paths)
    if not words:
        print("No words found.", file=sys.stderr)
        return 1

    report = build_report(words, top=args.top)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
