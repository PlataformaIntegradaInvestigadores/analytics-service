"""Create a new, explicitly synthetic corpus for HTTP/browser verification."""

import csv
import sys
from pathlib import Path

from app.data.centinela import FILES, ingest

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=False)
source = root / "exports"
source.mkdir()
rows = [
    [
        [
            "s1",
            "Controlled science title",
            "Useful controlled abstract energy solar research",
            "Alpha",
            "1",
            "2024-01-01",
            "a",
            "x",
            "2024",
        ],
        [
            "s2",
            "Controlled neural study",
            "Neural machine learning controlled research model",
            "Beta",
            "1",
            "2025-01-01",
            "a",
            "y",
            "2025",
        ],
    ],
    [["s1", "x"], ["s2", "y"]],
    [["alpha", "s1"], ["beta", "s2"]],
]
for (name, columns), table in zip(FILES.items(), rows, strict=True):
    with (source / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(table)
ingest(source, root / "corpus.sqlite")
(root / "worksets").mkdir()
