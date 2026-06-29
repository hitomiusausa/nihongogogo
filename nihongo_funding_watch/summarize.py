from __future__ import annotations

import re


SUMMARY_TERMS = (
    "公募",
    "募集",
    "企画競争",
    "プロポーザル",
    "委託",
    "補助金",
    "助成",
    "日本語教育",
    "認定日本語教育機関",
    "登録日本語教員",
    "在留資格",
    "特定技能",
    "育成就労",
    "技能実習",
    "留学生",
    "外国人材",
    "締切",
    "提出期限",
    "募集期間",
    "対象",
    "事業",
)

BOILERPLATE_PATTERNS = (
    "本文へ",
    "当サイトではJavaScriptを使用しております",
    "このサイトではJavaScriptを使用",
    "ご利用のブラウザ環境によっては",
    "ブラウザの設定でJavaScriptを有効",
    "Multi language",
    "文字サイズ",
    "標準",
    "拡大",
    "背景色",
    "検索",
    "MENU",
    "メニュー",
    "政策について",
    "文化行政の基盤",
    "文化庁の紹介",
    "各種助成金・支援制度一覧",
    "審議会・懇談会等",
    "ホーム >",
    "トップ >",
    "このページの先頭へ",
    "サイトマップ",
    "GoogleAnalyticsObject",
    "function(",
    "gtag(",
    "var ",
    "window.",
    "document.",
    "ファイル／",
    "KB]",
    "MB]",
    "申請様式",
    "交付申請書",
    "実績報告様式",
)


def summarize_detail(text: str, *, source_url: str, max_length: int = 260) -> str:
    snippets = relevant_snippets(text)
    body = " / ".join(snippets)
    if not body:
        body = fallback_body(text, max_length=max_length)
    body = normalize(body)
    if len(body) > max_length:
        body = body[: max_length - 1] + "…"
    return f"Source page: {source_url} / {body}" if body else f"Source page: {source_url}"


def relevant_snippets(text: str, *, limit: int = 3) -> list[str]:
    cleaned = normalize(text)
    if not cleaned:
        return []

    chunks = re.split(r"(?<=[。！？])|[\n\r]+|(?<=\s)(?=（\d+）)|(?<=\s)(?=\d+[．.])", cleaned)
    scored: list[tuple[int, str]] = []
    for chunk in chunks:
        chunk = normalize(chunk)
        if len(chunk) < 18:
            continue
        if is_boilerplate_chunk(chunk):
            continue
        score = sum(1 for term in SUMMARY_TERMS if term in chunk)
        if "Source page:" in chunk:
            score -= 2
        if score > 0:
            scored.append((score, chunk[:140]))

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    snippets: list[str] = []
    seen: set[str] = set()
    for _, snippet in scored:
        key = snippet[:36]
        if key in seen:
            continue
        seen.add(key)
        snippets.append(snippet)
        if len(snippets) >= limit:
            break
    return snippets


def fallback_body(text: str, *, max_length: int) -> str:
    chunks = re.split(r"[\n\r]+|(?<=[。！？])", text)
    for chunk in chunks:
        chunk = normalize(chunk)
        if len(chunk) >= 18 and not is_boilerplate_chunk(chunk):
            return chunk[:max_length]
    return normalize(text[:max_length])


def is_boilerplate_chunk(value: str) -> bool:
    if any(pattern in value for pattern in BOILERPLATE_PATTERNS):
        return True
    if len(value) > 120 and value.count("｜") >= 3:
        return True
    if len(value) > 120 and value.count(">") >= 3:
        return True
    return False


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
