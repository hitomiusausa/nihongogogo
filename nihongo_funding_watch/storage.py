from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .fetchers import FetchedItem, title_fingerprint
from .scoring import ScoredItem


# v2: title_fingerprint の正規化強化（NFKC・記号全落とし）に伴い title_key を全行再計算する。
SCHEMA_VERSION = 2

LEGACY_CATEGORY_MAP = {
    "ビザ・入管・在留資格": "ニュース（外国人・ビザ）",
    "日本語教育政策": "ニュース（日本語教育）",
    "営業候補": "その他",
    "未分類": "その他",
}


@dataclass(frozen=True)
class StoredItem:
    id: int
    title: str
    url: str
    source_name: str
    source_type: str
    published_at: str | None
    fetched_at: str
    summary: str
    primary_category: str
    categories: list[str]
    score: int
    matched_keywords: list[str]
    deadline_at: str | None = None
    country: str = ""
    dead_at: str | None = None


class WatchStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as db, db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    primary_category TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    matched_keywords_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_fetched_at ON items(fetched_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_category ON items(primary_category)"
            )
            if not column_exists(db, "items", "deadline_at"):
                db.execute("ALTER TABLE items ADD COLUMN deadline_at TEXT")
            if not column_exists(db, "items", "title_key"):
                db.execute("ALTER TABLE items ADD COLUMN title_key TEXT")
            if not column_exists(db, "items", "country"):
                db.execute("ALTER TABLE items ADD COLUMN country TEXT NOT NULL DEFAULT ''")
            if not column_exists(db, "items", "dead_at"):
                db.execute("ALTER TABLE items ADD COLUMN dead_at TEXT")
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_deadline_at ON items(deadline_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_title_key ON items(title_key)"
            )
            # Full-table data migrations only need to run once per schema bump,
            # not on every CLI invocation. Gate them behind PRAGMA user_version.
            current_version = db.execute("PRAGMA user_version").fetchone()[0]
            if current_version < SCHEMA_VERSION:
                migrate_legacy_categories(db)
                migrate_title_keys(db)
                prune_duplicate_title_keys(db)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def upsert_scored_item(self, scored: ScoredItem) -> bool:
        with closing(self.connect()) as db, db:
            return self._upsert(db, scored)

    def upsert_scored_items(self, scored_items: list[ScoredItem]) -> int:
        """Upsert many items in a single transaction. Returns the count of new rows."""
        stored_new = 0
        with closing(self.connect()) as db, db:
            for scored in scored_items:
                if self._upsert(db, scored):
                    stored_new += 1
        return stored_new

    def _upsert(self, db: sqlite3.Connection, scored: ScoredItem) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        item = scored.item
        item_title_key = title_fingerprint(item.title)
        existing = db.execute(
            """
            SELECT id FROM items
            WHERE url = ? OR (title_key IS NOT NULL AND title_key = ?)
            ORDER BY CASE WHEN url = ? THEN 0 ELSE 1 END, score DESC, fetched_at DESC
            LIMIT 1
            """,
            (item.url, item_title_key, item.url),
        ).fetchone()
        if existing:
            db.execute(
                """
                UPDATE items SET
                    title=?,
                    source_name=?,
                    source_type=?,
                    published_at=COALESCE(?, published_at),
                    summary=?,
                    fetched_at=?,
                    primary_category=?,
                    categories_json=?,
                    score=MAX(score, ?),
                    matched_keywords_json=?,
                    deadline_at=COALESCE(?, deadline_at),
                    title_key=?,
                    country=?
                WHERE id=?
                """,
                (
                    item.title,
                    item.source_name,
                    item.source_type,
                    item.published_at.isoformat() if item.published_at else None,
                    item.summary,
                    now,
                    scored.primary_category,
                    json.dumps(scored.categories, ensure_ascii=False),
                    scored.score,
                    json.dumps(scored.matched_keywords, ensure_ascii=False),
                    scored.deadline_at,
                    item_title_key,
                    item.country,
                    existing["id"],
                ),
            )
            return False

        db.execute(
            """
            INSERT INTO items (
                title, url, source_name, source_type, published_at, fetched_at,
                summary, primary_category, categories_json, score,
                matched_keywords_json, deadline_at, title_key, country
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                source_name=excluded.source_name,
                source_type=excluded.source_type,
                published_at=COALESCE(excluded.published_at, items.published_at),
                summary=excluded.summary,
                primary_category=excluded.primary_category,
                categories_json=excluded.categories_json,
                score=MAX(items.score, excluded.score),
                matched_keywords_json=excluded.matched_keywords_json,
                deadline_at=COALESCE(excluded.deadline_at, items.deadline_at),
                title_key=excluded.title_key,
                country=excluded.country
            """,
            (
                item.title,
                item.url,
                item.source_name,
                item.source_type,
                item.published_at.isoformat() if item.published_at else None,
                now,
                item.summary,
                scored.primary_category,
                json.dumps(scored.categories, ensure_ascii=False),
                scored.score,
                json.dumps(scored.matched_keywords, ensure_ascii=False),
                scored.deadline_at,
                item_title_key,
                item.country,
            ),
        )
        return True

    def recent_items(
        self, *, since_days: int = 10, include_dead: bool = False
    ) -> list[StoredItem]:
        threshold = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        dead_filter = "" if include_dead else "AND dead_at IS NULL"
        with closing(self.connect()) as db:
            rows = db.execute(
                f"""
                SELECT * FROM items
                WHERE (fetched_at >= ? OR published_at >= ?) {dead_filter}
                ORDER BY score DESC, COALESCE(published_at, fetched_at) DESC
                """,
                (threshold, threshold),
            ).fetchall()
        return [row_to_item(row) for row in rows]

    def mark_dead(self, url: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE items SET dead_at = COALESCE(dead_at, ?) WHERE url = ?",
                (now, url),
            )

    def clear_dead(self, url: str) -> None:
        with closing(self.connect()) as db, db:
            db.execute("UPDATE items SET dead_at = NULL WHERE url = ?", (url,))

    def all_items(self) -> list[StoredItem]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT * FROM items ORDER BY fetched_at DESC, score DESC"
            ).fetchall()
        return [row_to_item(row) for row in rows]

    def duplicate_groups(self) -> list[tuple[str, int, str]]:
        with closing(self.connect()) as db:
            rows = db.execute(
                """
                SELECT title_key, COUNT(*) AS count, MIN(title) AS sample_title
                FROM items
                WHERE title_key IS NOT NULL AND title_key != ''
                GROUP BY title_key
                HAVING COUNT(*) > 1
                ORDER BY count DESC, sample_title
                """
            ).fetchall()
        return [
            (str(row["title_key"]), int(row["count"]), str(row["sample_title"]))
            for row in rows
        ]


def row_to_item(row: sqlite3.Row) -> StoredItem:
    categories = [
        normalize_category(category)
        for category in json.loads(row["categories_json"])
    ]
    return StoredItem(
        id=int(row["id"]),
        title=str(row["title"]),
        url=str(row["url"]),
        source_name=str(row["source_name"]),
        source_type=str(row["source_type"]),
        published_at=row["published_at"],
        fetched_at=str(row["fetched_at"]),
        summary=str(row["summary"]),
        primary_category=normalize_category(str(row["primary_category"])),
        categories=categories,
        score=int(row["score"]),
        matched_keywords=json.loads(row["matched_keywords_json"]),
        deadline_at=row["deadline_at"],
        country=str(row["country"]) if "country" in row.keys() else "",
        dead_at=row["dead_at"] if "dead_at" in row.keys() else None,
    )


def column_exists(db: sqlite3.Connection, table: str, column: str) -> bool:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def normalize_category(category: str) -> str:
    return LEGACY_CATEGORY_MAP.get(category, category)


def migrate_legacy_categories(db: sqlite3.Connection) -> None:
    for old, new in LEGACY_CATEGORY_MAP.items():
        db.execute(
            "UPDATE items SET primary_category = ? WHERE primary_category = ?",
            (new, old),
        )

    rows = db.execute("SELECT id, categories_json FROM items").fetchall()
    for row in rows:
        try:
            categories = json.loads(row["categories_json"])
        except json.JSONDecodeError:
            categories = ["その他"]
        normalized = [normalize_category(str(category)) for category in categories]
        if normalized != categories:
            db.execute(
                "UPDATE items SET categories_json = ? WHERE id = ?",
                (json.dumps(normalized, ensure_ascii=False), row["id"]),
            )


def migrate_title_keys(db: sqlite3.Connection) -> None:
    # title_key は常に title_fingerprint(title) と一致させる。指紋の定義が変わった
    # スキーマ更新時にも全行を現行定義で再計算する（残すと旧定義のキーで重複が漏れる）。
    rows = db.execute("SELECT id, title, title_key FROM items").fetchall()
    for row in rows:
        key = title_fingerprint(str(row["title"]))
        if key != row["title_key"]:
            db.execute(
                "UPDATE items SET title_key = ? WHERE id = ?",
                (key, row["id"]),
            )


def prune_duplicate_title_keys(db: sqlite3.Connection) -> None:
    groups = db.execute(
        """
        SELECT title_key
        FROM items
        WHERE title_key IS NOT NULL AND title_key != ''
        GROUP BY title_key
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for group in groups:
        rows = db.execute(
            """
            SELECT id
            FROM items
            WHERE title_key = ?
            ORDER BY score DESC, fetched_at DESC, id ASC
            """,
            (group["title_key"],),
        ).fetchall()
        keep_id = rows[0]["id"]
        duplicate_ids = [row["id"] for row in rows[1:]]
        if duplicate_ids:
            db.executemany(
                "DELETE FROM items WHERE id = ?",
                [(item_id,) for item_id in duplicate_ids],
            )
