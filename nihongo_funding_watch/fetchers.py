from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from .config import PageSource


USER_AGENT = (
    "Semiosis-NihongoFundingWatch/0.1 "
    "(https://fingerboard-app.com/nihongo_catch/)"
)


@dataclass(frozen=True)
class FetchedItem:
    title: str
    url: str
    source_name: str
    source_type: str
    published_at: datetime | None = None
    summary: str = ""


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self._current_href: str | None = None
        self._parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        self._current_href = urllib.parse.urljoin(self.base_url, href)
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._parts.append(data)
        cleaned = normalize_text(data)
        if cleaned:
            self.text_parts.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return
        title = normalize_text(" ".join(self._parts))
        if title:
            self.links.append((title, self._current_href))
        self._current_href = None
        self._parts = []


def fetch_google_news(query: str, *, pause_seconds: float = 0.2) -> list[FetchedItem]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
        }
    )
    url = f"https://news.google.com/rss/search?{params}"
    body = http_get(url)
    time.sleep(pause_seconds)
    return parse_rss(body, source_name=f"Google News: {query}", source_type="google_news")


def fetch_page_links(source: PageSource, *, pause_seconds: float = 0.2) -> list[FetchedItem]:
    body = http_get(source.url)
    time.sleep(pause_seconds)
    if source.parser == "bunka_kobo":
        return limit_items(parse_bunka_kobo(body, source), source.max_links)
    if source.parser == "mext_boshu":
        return limit_items(parse_mext_boshu(body, source), source.max_links)
    if source.parser == "municipality_focus":
        return limit_items(parse_municipality_focus(body, source), source.max_links)

    parser = LinkExtractor(source.url)
    parser.feed(body.decode("utf-8", errors="replace"))
    items: list[FetchedItem] = []
    seen: set[str] = set()
    for title, url in parser.links:
        clean_url = canonicalize_url(url)
        if clean_url in seen:
            continue
        if source.allow_url_patterns and not any(
            re.search(pattern, clean_url) for pattern in source.allow_url_patterns
        ):
            continue
        seen.add(clean_url)
        items.append(
            FetchedItem(
                title=title,
                url=clean_url,
                source_name=source.name,
                source_type="page",
                summary=f"Source page: {source.url}",
            )
        )
        if source.max_links is not None and len(items) >= source.max_links:
            break
    return items


def parse_bunka_kobo(body: bytes, source: PageSource) -> list[FetchedItem]:
    text = body.decode("utf-8", errors="replace")
    main = slice_between(text, '<div id="main_contents">', "<!-- /main_contents -->")
    items: list[FetchedItem] = []
    seen: set[str] = set()
    for block in re.findall(r'<div class="article">(.*?)</div>', main, flags=re.S):
        section = strip_tags(first_match(block, r'<h2[^>]*>.*?<span>(.*?)</span>.*?</h2>'))
        if "過去" in section:
            continue
        for href, raw_title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S):
            title = strip_tags(raw_title)
            url = canonicalize_url(urllib.parse.urljoin(source.url, html.unescape(href)))
            if not title or url in seen:
                continue
            if source.allow_url_patterns and not any(
                re.search(pattern, url) for pattern in source.allow_url_patterns
            ):
                continue
            seen.add(url)
            summary_parts = [f"Source page: {source.url}"]
            if section:
                summary_parts.append(f"一覧区分: {section}")
            items.append(
                FetchedItem(
                    title=title,
                    url=url,
                    source_name=source.name,
                    source_type="page",
                    summary=" / ".join(summary_parts),
                )
            )
    return items


def parse_mext_boshu(body: bytes, source: PageSource) -> list[FetchedItem]:
    text = body.decode("utf-8", errors="replace")
    items: list[FetchedItem] = []
    seen: set[str] = set()
    for section_match in re.finditer(
        r'<h3[^>]*>\s*<a[^>]+id="information\d+"[^>]*></a>\s*公募情報\s*</h3>(.*?)(?:<!-- /カテゴリ別一覧（公募情報） -->|<h3)',
        text,
        flags=re.S,
    ):
        section = section_match.group(1)
        for date_text, href, raw_title in re.findall(
            r"<dl>\s*<dt>(.*?)</dt>\s*<dd>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*</dd>\s*</dl>",
            section,
            flags=re.S,
        ):
            title = strip_tags(raw_title)
            url = canonicalize_url(urllib.parse.urljoin(source.url, html.unescape(href)))
            if not title or url in seen:
                continue
            if source.allow_url_patterns and not any(
                re.search(pattern, url) for pattern in source.allow_url_patterns
            ):
                continue
            seen.add(url)
            listed_date = strip_tags(date_text)
            summary = f"Source page: {source.url} / 一覧掲載日: {listed_date}"
            items.append(
                FetchedItem(
                    title=title,
                    url=url,
                    source_name=source.name,
                    source_type="page",
                    published_at=parse_japanese_date(listed_date),
                    summary=summary,
                )
            )
    return items


def parse_municipality_focus(body: bytes, source: PageSource) -> list[FetchedItem]:
    text = body.decode("utf-8", errors="replace")
    parser = LinkExtractor(source.url)
    parser.feed(text)
    page_text = normalize_text(" ".join(parser.text_parts))
    self_item: FetchedItem | None = None
    items: list[FetchedItem] = []
    seen: set[str] = set()

    title = municipality_page_title(text, page_text)
    if title and municipality_relevant(title, page_text):
        self_item = FetchedItem(
            title=title,
            url=canonicalize_url(source.url),
            source_name=source.name,
            source_type="page",
            published_at=parse_japanese_or_western_date(page_text),
            summary=municipality_summary(source.url, title, page_text),
        )
        seen.add(canonicalize_url(source.url))

    for link_title, url in parser.links:
        clean_url = canonicalize_url(url)
        title = strip_tags(link_title)
        if clean_url in seen or not title:
            continue
        if is_attachment_url(clean_url):
            continue
        if source.allow_url_patterns and not any(
            re.search(pattern, clean_url) for pattern in source.allow_url_patterns
        ):
            continue
        if not municipality_relevant(title, ""):
            continue
        seen.add(clean_url)
        items.append(
            FetchedItem(
                title=title,
                url=clean_url,
                source_name=source.name,
                source_type="page",
                summary=f"Source page: {source.url}",
            )
        )
    if self_item and not any(is_related_title(self_item.title, item.title) for item in items):
        items.insert(0, self_item)
    return items


def fetch_page_text(url: str, *, max_chars: int = 12000) -> str:
    body = http_get(url)
    parser = LinkExtractor(url)
    parser.feed(body.decode("utf-8", errors="replace"))
    text = normalize_text(" ".join(parser.text_parts))
    return text[:max_chars]


def http_get(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc.reason}") from exc


def parse_rss(body: bytes, *, source_name: str, source_type: str) -> list[FetchedItem]:
    root = ET.fromstring(body)
    items: list[FetchedItem] = []
    for item in root.findall(".//item"):
        title = text_of(item, "title")
        link = text_of(item, "link")
        description = strip_tags(text_of(item, "description"))
        published = parse_datetime(text_of(item, "pubDate"))
        if not title or not link:
            continue
        if source_type == "google_news":
            title = clean_google_news_title(title)
        items.append(
            FetchedItem(
                title=html.unescape(title),
                url=canonicalize_url(link),
                source_name=source_name,
                source_type=source_type,
                published_at=published,
                summary=html.unescape(description),
            )
        )
    return items


def clean_google_news_title(title: str) -> str:
    title = html.unescape(title)
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def text_of(element: ET.Element, child_name: str) -> str:
    child = element.find(child_name)
    return child.text.strip() if child is not None and child.text else ""


def strip_tags(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    return normalize_text(html.unescape(no_tags))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def title_fingerprint(title: str) -> str:
    value = clean_google_news_title(title)
    value = re.sub(r"（[^）]{1,30}）|\([^)]{1,30}\)", "", value)
    value = re.sub(r"[\s　、。，．・:：;；!！?？「」『』【】\[\]（）()]", "", value)
    return value.lower()


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_japanese_date(value: str) -> datetime | None:
    match = re.search(r"(令和|平成)(\d+|元)年(\d{1,2})月(\d{1,2})日", value)
    if not match:
        return None
    era, year_text, month_text, day_text = match.groups()
    era_start = {"令和": 2018, "平成": 1988}.get(era)
    if era_start is None:
        return None
    year = era_start + (1 if year_text == "元" else int(year_text))
    return datetime(year, int(month_text), int(day_text), tzinfo=UTC)


def parse_japanese_or_western_date(value: str) -> datetime | None:
    parsed = parse_japanese_date(value)
    if parsed:
        return parsed
    match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", value)
    if not match:
        return None
    year, month, day = match.groups()
    return datetime(int(year), int(month), int(day), tzinfo=UTC)


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query_pairs = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"ved", "usg"}
    ]
    query = urllib.parse.urlencode(query_pairs)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, query, "")
    )


def first_match(value: str, pattern: str) -> str:
    match = re.search(pattern, value, flags=re.S)
    return match.group(1) if match else ""


def slice_between(value: str, start_marker: str, end_marker: str) -> str:
    start = value.find(start_marker)
    if start < 0:
        return value
    end = value.find(end_marker, start)
    return value[start:] if end < 0 else value[start:end]


def limit_items(items: list[FetchedItem], max_links: int | None) -> list[FetchedItem]:
    return items if max_links is None else items[:max_links]


def municipality_page_title(text: str, page_text: str) -> str:
    heading_titles: list[str] = []
    for pattern in [
        r"<h1[^>]*>(.*?)</h1>",
        r"<title[^>]*>(.*?)</title>",
    ]:
        title = strip_tags(first_match(text, pattern))
        if title:
            heading_titles.append(clean_page_title(title))

    for title in heading_titles:
        if municipality_relevant(title, ""):
            return title

    return ""


def municipality_focus_phrase(page_text: str) -> str:
    patterns = [
        r"「([^」]{6,90}(?:補助金|助成|奨励金|委託事業|受託事業者|連携先事業者)[^」]{0,30})」",
        r"((?:令和|20)\S{0,12}(?:補助金|助成|奨励金|委託事業|受託事業者|連携先事業者)[^。]{0,55})",
        r"([^。]{0,45}(?:補助金|助成|奨励金|委託事業|受託事業者|連携先事業者)[^。]{0,45})",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text)
        if match:
            return clean_page_title(match.group(1))
    return ""


def clean_page_title(value: str) -> str:
    value = normalize_text(value)
    is_closed = "終了" in value
    value = re.sub(r"\s*[-|｜／].*$", "", value).strip()
    value = re.sub(r"\s+ページID：.*$", "", value).strip()
    value = re.sub(r"\s+記事ID：.*$", "", value).strip()
    value = re.sub(r"^詳細はこちら\s*", "", value).strip()
    value = re.sub(r"^【[^】]+】", "", value).strip()
    for term in ["補助金", "助成", "奨励金"]:
        index = value.find(term)
        if index >= 0:
            title = value[: index + len(term)].strip("「」 　")
            return f"{title}（受付終了）" if is_closed and "終了" not in title else title
    title = value[:120]
    return f"{title}（受付終了）" if is_closed and "終了" not in title else title


def municipality_relevant(title: str, context: str) -> bool:
    text = f"{title}\n{context}"
    if any(term in title for term in ["セミナー", "フェア", "講座", "研修", "面接会", "交流会"]):
        if not any(term in title for term in ["補助金", "助成", "委託", "プロポーザル"]):
            return False
    public_signal = any(
        term in text
        for term in [
            "補助金",
            "補助",
            "助成",
            "奨励金",
            "委託",
            "委託事業",
            "受託事業者",
            "プロポーザル",
            "企画提案",
            "公募",
            "交付金",
            "連携先事業者",
        ]
    )
    domain_signal = any(
        term in text
        for term in [
            "日本語",
            "日本語教育",
            "外国人材",
            "外国人",
            "留学生",
            "特定技能",
            "介護人材",
            "多文化共生",
            "外国人活躍",
        ]
    )
    return public_signal and domain_signal


def municipality_summary(source_url: str, title: str, page_text: str) -> str:
    excerpt = title if municipality_relevant(title, "") else municipality_focus_phrase(page_text)
    if not excerpt:
        excerpt = page_text[:220]
    return f"Source page: {source_url} / {excerpt}"


def is_attachment_url(url: str) -> bool:
    return bool(re.search(r"\.(pdf|xlsx?|docx?|pptx?|zip)(?:$|\?)", url, flags=re.I))


def is_related_title(left: str, right: str) -> bool:
    left_key = title_fingerprint(left)
    right_key = title_fingerprint(right)
    if not left_key or not right_key:
        return False
    return left_key in right_key or right_key in left_key
