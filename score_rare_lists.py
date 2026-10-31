#!/usr/bin/env python3
from src.models import rarity_points
from pathlib import Path

out_dir = Path("data/word_lists")
counts = {}
high = []

for f in sorted(out_dir.glob("rare_*.txt")):
    names = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    scores = [(n, rarity_points(n)) for n in names]
    ge500 = [(n, s) for n, s in scores if s >= 500]
    counts[f.name] = {
        "total": len(scores),
        ">=500": len(ge500),
        "max": max((s for _, s in scores), default=0),
    }
    high.extend([(f.name, n, s) for n, s in ge500])

for name, info in sorted(counts.items()):
    print(f"{name}: {info['total']} total, {info['>=500']} >=500, max {info['max']}")

print("\nSample high scores:")
for fn, n, s in sorted(high, key=lambda x: -x[2])[:30]:
    print(f"  {n} ({s}) from {fn}")
