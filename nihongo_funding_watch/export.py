from __future__ import annotations

import csv
from pathlib import Path

from .storage import WatchStore


def export_csv(store: WatchStore, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "title",
                "url",
                "source_name",
                "source_type",
                "country",
                "published_at",
                "fetched_at",
                "primary_category",
                "categories",
                "score",
                "matched_keywords",
                "deadline_at",
                "summary",
            ]
        )
        for item in store.all_items():
            writer.writerow(
                [
                    item.id,
                    item.title,
                    item.url,
                    item.source_name,
                    item.source_type,
                    item.country,
                    item.published_at,
                    item.fetched_at,
                    item.primary_category,
                    ";".join(item.categories),
                    item.score,
                    ";".join(item.matched_keywords),
                    item.deadline_at,
                    item.summary,
                ]
            )
