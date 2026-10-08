"""新着記事に Claude の要約・関連度・営業の切り口を付ける（AI要約）。

コアパッケージは標準ライブラリだけで動かすため、anthropic SDK は関数内で遅延 import する。
SDK 未導入・ANTHROPIC_API_KEY 未設定なら一行メッセージを出して何もせず正常終了する。
日次ジョブを絶対に落とさないよう、例外は記事ごとに捕まえる。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

from .fetchers import fetch_page_text
from .storage import StoredItem, WatchStore


# ---- 制限値・定数 -------------------------------------------------------------
MODEL = "claude-sonnet-5-5"
DEFAULT_LIMIT = 40  # 1回の実行で処理する最大件数（新着は1日2〜7件程度）
MAX_PAGE_TEXT_CHARS = 6000  # 本文はこの文字数で打ち切って渡す（コストと入力の上限）
MAX_TOKENS = 4000
EFFORT = "medium"
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"
PAGE_FETCH_PAUSE_SECONDS = 0.2  # 本文取得の間隔（相手サイトへの配慮）
API_KEY_ENV = "ANTHROPIC_API_KEY"

PUBLIC_CATEGORY = "公募・補助金・プロポーザル"
RELEVANCE_LEVELS = ["高", "中", "低", "無関係"]
IRRELEVANT = "無関係"

# 拒否・打ち切りは同じ入力で再試行しても結果が変わりにくいので「試行済み」にする。
NO_CONTENT_STOP_REASONS = {"refusal", "max_tokens"}
# 認証・権限エラーは全件同じ結果になるので実行ごと打ち切る。
ABORT_ERROR_NAMES = {"AuthenticationError", "PermissionDeniedError"}
# 一時的なエラーは未試行のまま残し、翌日の実行で再挑戦する。
RETRY_ERROR_NAMES = {"RateLimitError", "APIStatusError", "APIConnectionError"}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "relevance": {"type": "string", "enum": RELEVANCE_LEVELS},
        "sales_hint": {"type": "string"},
    },
    "required": ["summary", "relevance", "sales_hint"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """あなたは Semiosis株式会社 の調査アシスタントです。
Semiosis は日本語学習サービス「Nihongo Catch!」を提供しており、育成就労・特定技能で働く外国人の日本語講習や、登録支援機関・受入企業への営業も行っています。
収集した記事1件について、資金獲得（公募・補助金）と政策動向の把握に役立つ情報を JSON で返してください。

- summary: 2文以内の日本語。何の話か、誰が対象か、締切や金額が入力に書かれていればそれも含める。入力に無い事実（日付・金額・団体名など）は絶対に作らない。分からないことは書かない。
- relevance: 日本語教育・外国人材・在留資格・公募/補助金との関係の強さを「高」「中」「低」「無関係」から選ぶ。旅行割引（全国旅行支援など）や無関係な一般ニュースは「無関係」。
- sales_hint: primary_category が「公募・補助金・プロポーザル」のときだけ、Nihongo Catch! としてどう応募・提案できそうかを1行で書く。それ以外のカテゴリでは必ず空文字にする。
"""


@dataclass(frozen=True)
class EnrichResult:
    enriched: int = 0
    skipped: int = 0  # 試行したが内容なし（拒否・打ち切り・JSON不正）
    failed: int = 0  # 一時エラーで未試行のまま残したもの
    skip_reason: str = ""  # SDK/キー無しで全体をスキップした理由
    aborted: str = ""  # 認証エラー等で途中打ち切りした理由


def enrich_items(
    store: WatchStore,
    *,
    limit: int = DEFAULT_LIMIT,
    client: Any = None,
    page_text_fetcher: Callable[[str], str] | None = None,
    log: Callable[[str], None] | None = None,
) -> EnrichResult:
    """未処理の記事に AI 要約を付けて保存する。client はテスト用に差し込める。"""
    log = log or _log_stderr
    if client is None:
        if not os.environ.get(API_KEY_ENV):
            return EnrichResult(skip_reason=f"{API_KEY_ENV} が未設定のためAI要約をスキップ")
        try:
            import anthropic  # 遅延 import: コアは標準ライブラリだけで動かす
        except ImportError:
            return EnrichResult(
                skip_reason="anthropic SDK が未インストールのためAI要約をスキップ"
                "（pip install -r requirements-ai.txt）"
            )
        client = anthropic.Anthropic()
    fetcher = page_text_fetcher or _default_page_text

    enriched = skipped = failed = 0
    for item in store.items_needing_enrichment(limit):
        page_text = ""
        if should_fetch_page(item):
            try:
                page_text = fetcher(item.url)[:MAX_PAGE_TEXT_CHARS]
            except Exception:  # noqa: BLE001 - 本文が取れなくても保存済みの項目で続ける
                page_text = ""
            time.sleep(PAGE_FETCH_PAUSE_SECONDS)

        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                betas=BETAS,
                fallbacks=FALLBACKS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_text(item, page_text)}],
                output_config={
                    "effort": EFFORT,
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
            )
        except Exception as exc:  # noqa: BLE001 - 日次ジョブを落とさない
            kind = error_kind(exc)
            request_id = getattr(exc, "request_id", None)
            message = f"AI要約失敗 id={item.id} {type(exc).__name__}: {exc} request_id={request_id}"
            if kind == "abort":
                log(f"{message} → 認証/権限エラーのため実行を打ち切り")
                return EnrichResult(
                    enriched=enriched,
                    skipped=skipped,
                    failed=failed,
                    aborted=f"{type(exc).__name__}（APIキー・権限を確認）",
                )
            log(message)
            failed += 1
            continue

        parsed = parse_response(response)
        model_used = str(getattr(response, "model", "") or MODEL)
        if parsed is None:
            log(
                f"AI要約なし id={item.id} stop_reason={getattr(response, 'stop_reason', None)} "
                f"request_id={getattr(response, '_request_id', None)}"
            )
            store.save_enrichment(
                item.id, summary="", relevance=None, sales_hint="", model=model_used
            )
            skipped += 1
            continue

        summary, relevance, sales_hint = parsed
        if item.primary_category != PUBLIC_CATEGORY:
            sales_hint = ""
        store.save_enrichment(
            item.id,
            summary=summary,
            relevance=relevance,
            sales_hint=sales_hint,
            model=model_used,
        )
        enriched += 1

    return EnrichResult(enriched=enriched, skipped=skipped, failed=failed)


def parse_response(response: Any) -> tuple[str, str | None, str] | None:
    """stop_reason を先に見て、内容が使えるときだけ (summary, relevance, sales_hint) を返す。"""
    if getattr(response, "stop_reason", None) in NO_CONTENT_STOP_REASONS:
        return None
    text = next(
        (block.text for block in getattr(response, "content", []) or [] if getattr(block, "type", "") == "text"),
        None,
    )
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    relevance = data.get("relevance")
    if relevance not in RELEVANCE_LEVELS:
        relevance = None
    sales_hint = str(data.get("sales_hint") or "").strip()
    return summary, relevance, sales_hint


def error_kind(exc: BaseException) -> str:
    """SDK の例外を import せずにクラス名（継承元含む）で分類する。"""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & ABORT_ERROR_NAMES:
        return "abort"
    if names & RETRY_ERROR_NAMES:
        return "retry"
    return "other"


def should_fetch_page(item: StoredItem) -> bool:
    """Google News のリダイレクトURLは本文が取れないので取得しない。"""
    if item.source_type == "google_news":
        return False
    parsed = urllib.parse.urlsplit(item.url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return not parsed.netloc.endswith("news.google.com")


def build_user_text(item: StoredItem, page_text: str) -> str:
    lines = [
        f"title: {item.title}",
        f"source_name: {item.source_name}",
        f"primary_category: {item.primary_category}",
        f"published_at: {item.published_at or '不明'}",
        f"deadline_at: {item.deadline_at or '不明'}",
        f"existing_summary: {item.summary or '(なし)'}",
        f"url: {item.url}",
    ]
    if page_text:
        lines.append("")
        lines.append(f"page_text（先頭{MAX_PAGE_TEXT_CHARS}文字まで）:")
        lines.append(page_text)
    else:
        lines.append("page_text: (取得なし。上の項目だけで判断すること)")
    return "\n".join(lines)


def _default_page_text(url: str) -> str:
    return fetch_page_text(url, max_chars=MAX_PAGE_TEXT_CHARS)


def _log_stderr(message: str) -> None:
    print(f"  {message}", file=sys.stderr)
