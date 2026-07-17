from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from html import escape
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

from .config import WatchConfig
from .deadlines import days_until, parse_iso_date
from .report import select_display_groups
from .storage import StoredItem, WatchStore


JST = ZoneInfo("Asia/Tokyo")
CATEGORY_ORDER = [
    "公募・補助金・プロポーザル",
    "ニュース（日本語教育）",
    "ニュース（外国人・ビザ）",
    "その他",
]
RECENTLY_EXPIRED_DAYS = 30
ARCHIVE_AFTER_DAYS = 180


def write_site(
    config: WatchConfig,
    store: WatchStore,
    site_dir: Path,
    *,
    since_days: int = 10,
) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = site_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(JST).date().isoformat()
    groups = select_display_groups(config, store, since_days=since_days)
    items = [group.item for group in groups]
    related_map = {group.item.id: group.related for group in groups if group.related}
    html = render_site(config, items, since_days=since_days, related_map=related_map)

    dated_path = reports_dir / f"{today}.html"
    index_path = site_dir / "index.html"
    copy_site_assets(site_dir)
    dated_path.write_text(html, encoding="utf-8")
    index_path.write_text(html, encoding="utf-8")
    return index_path


def copy_site_assets(site_dir: Path) -> None:
    source_dir = Path(__file__).resolve().parent.parent / "images"
    if not source_dir.exists():
        return
    target_dir = site_dir / "images"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ["nihongogogogo.png", "nihongogogogo3.png", "nihongogogogo4.png"]:
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, target_dir / name)


def render_site(
    config: WatchConfig,
    items: list[StoredItem],
    *,
    since_days: int = 10,
    related_map: dict[int, list[StoredItem]] | None = None,
) -> str:
    now = datetime.now(JST)
    today = now.date()
    visible_items = [
        item
        for item in items
        if not is_archived(item, today=today)
    ]
    grouped: dict[str, list[StoredItem]] = defaultdict(list)
    for item in visible_items:
        grouped[item.primary_category].append(item)
    with_deadlines = [item for item in visible_items if item.deadline_at]
    urgent_items = [
        item
        for item in visible_items
        if (remaining := days_until(parse_iso_date(item.deadline_at), today=today)) is not None
        and 0 <= remaining <= 30
    ]
    recently_expired_items = [
        item
        for item in visible_items
        if is_recently_expired(item, today=today)
    ]
    expired_items = [
        item
        for item in visible_items
        if is_expired(item, today=today)
    ]

    reflected_today = [
        item for item in visible_items if format_date(item.fetched_at) == now.date().isoformat()
    ]
    sections = [(category, grouped.get(category, [])) for category in CATEGORY_ORDER]
    related_map = related_map or {}

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>日本語教育 資金・政策ウォッチ</title>
  <link rel="icon" type="image/png" href="images/nihongogogogo3.png">
  <link rel="apple-touch-icon" href="images/nihongogogogo3.png">
  <style>
    :root {{
      color-scheme: light;
      --pink: #F4C6C3;
      --green: #A2D5AB;
      --cream: #F9F7F0;
      --blue: #A7D8F0;
      --yellow: #FCE77C;
      --coral: #F8AFA6;
      --header: #A7D8F0;
      --bg: var(--cream);
      --ink: #253036;
      --muted: #687276;
      --line: #ded7c7;
      --paper: #fffdf8;
      --soft: var(--yellow);
      --accent: #2d6f7d;
      --accent-2: #8d4b43;
      --danger: #b8392f;
      --warning: #866500;
      --good: #236d3a;
      --proposal: var(--coral);
      --education: var(--blue);
      --visa: var(--green);
      --other: var(--yellow);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      -webkit-text-size-adjust: 100%;
      text-size-adjust: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
      background-color: var(--bg);
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='112' height='112' viewBox='0 0 112 112'%3E%3Crect width='112' height='112' fill='%23F9F7F0'/%3E%3Crect x='0' y='0' width='56' height='56' fill='%23A7D8F0' fill-opacity='.18'/%3E%3Crect x='56' y='0' width='56' height='56' fill='%23FCE77C' fill-opacity='.18'/%3E%3Crect x='0' y='56' width='56' height='56' fill='%23A2D5AB' fill-opacity='.16'/%3E%3Crect x='56' y='56' width='56' height='56' fill='%23F4C6C3' fill-opacity='.18'/%3E%3C/svg%3E");
      background-size: 112px 112px;
      color: var(--ink);
      line-height: 1.55;
    }}
    header {{
      padding: 56px 20px 40px;
      border-bottom: 1px solid var(--line);
      background:
        linear-gradient(rgba(249, 247, 240, 0.5), rgba(249, 247, 240, 0.62)),
        url("images/nihongogogogo4.png") center / cover no-repeat,
        var(--header);
      position: sticky;
      top: 0;
      z-index: 2;
      overflow: hidden;
    }}
    main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto 56px; }}
    .top {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; position: relative; z-index: 1; }}
    h1 {{ margin: 0 0 6px; font-size: clamp(24px, 3vw, 34px); line-height: 1.18; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; letter-spacing: 0; }}
    .meta {{ color: var(--muted); margin: 0; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 16px; }}
    .stat {{
      aspect-ratio: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 8px;
      border: 2px solid var(--blue);
      background: rgba(255, 253, 246, 0.4);
      border-radius: 50%;
    }}
    .stat:nth-child(2) {{ border-color: var(--coral); }}
    .stat:nth-child(3) {{ border-color: var(--green); }}
    .stat:nth-child(4) {{ border-color: var(--yellow); }}
    .stat:nth-child(5) {{ border-color: var(--pink); }}
    .stat:nth-child(6) {{ border-color: var(--blue); }}
    .stat strong {{ display: block; font-size: 23px; color: var(--accent); line-height: 1.2; }}
    .controls {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 10px;
      margin: 18px 0 0;
      align-items: center;
    }}
    .search {{
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      font: inherit;
      background: var(--paper);
    }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .filter {{
      border: 1px solid var(--line);
      background: var(--paper);
      color: var(--ink);
      border-radius: 8px;
      height: 36px;
      padding: 0 10px;
      cursor: pointer;
      font: inherit;
      font-size: 13px;
    }}
    .filter.active {{ background: var(--coral); color: #8d2f25; border-color: var(--coral); font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
    .list {{ display: grid; gap: 10px; }}
    article {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      min-width: 0;
      box-shadow: 0 1px 0 rgba(20, 30, 20, 0.04);
    }}
    article.urgent {{ border-left: 4px solid var(--danger); }}
    article.expired {{ opacity: 0.68; }}
    article.expired-recent {{ opacity: 1; }}
    article.expired-old[hidden] {{ display: none; }}
    article.cat-proposal {{ border-top: 4px solid var(--proposal); }}
    article.cat-education {{ border-top: 4px solid var(--education); }}
    article.cat-visa {{ border-top: 4px solid var(--visa); }}
    article.cat-other {{ border-top: 4px solid var(--other); }}
    a {{ color: #064f85; text-decoration-thickness: 1px; text-underline-offset: 2px; overflow-wrap: anywhere; word-break: break-word; }}
    .title {{ font-weight: 700; font-size: 15px; margin: 0 0 8px; overflow-wrap: anywhere; }}
    .item-meta {{ color: var(--muted); font-size: 13px; margin: 0 0 8px; }}
    .row {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 8px; align-items: center; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: #f8faf7;
      color: var(--muted);
    }}
    .badge.deadline {{ color: #25556a; background: rgba(167, 216, 240, 0.35); border-color: var(--blue); }}
    .badge.urgent {{ color: var(--danger); background: rgba(248, 175, 166, 0.32); border-color: var(--coral); }}
    .badge.soon {{ color: var(--warning); background: rgba(252, 231, 124, 0.44); border-color: var(--yellow); }}
    .badge.expired-recent {{ color: #7d3b00; background: rgba(244, 198, 195, 0.36); border-color: var(--pink); }}
    .badge.expired {{ color: #66616a; background: #f1eef2; border-color: #d7cedb; }}
    .badge.cat-proposal {{ color: #8d352b; background: rgba(248, 175, 166, 0.34); border-color: var(--coral); }}
    .badge.cat-education {{ color: #25556a; background: rgba(167, 216, 240, 0.36); border-color: var(--blue); }}
    .badge.cat-visa {{ color: #286337; background: rgba(162, 213, 171, 0.38); border-color: var(--green); }}
    .badge.cat-other {{ color: #6f5a00; background: rgba(252, 231, 124, 0.46); border-color: var(--yellow); }}
    .badge.country {{ color: #4b3b7a; background: rgba(244, 198, 195, 0.42); border-color: var(--pink); font-weight: 700; }}
    .angle {{ margin: 8px 0 0; font-size: 13px; color: #315b35; border-top: 1px solid var(--line); padding-top: 8px; }}
    .summary {{ color: #3c4043; font-size: 13px; margin: 8px 0 0; overflow-wrap: anywhere; }}
    .related {{ color: var(--muted); font-size: 12px; margin: 8px 0 0; overflow-wrap: anywhere; }}
    .tag {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 8px;
      margin: 2px 4px 2px 0;
      font-size: 12px;
      color: var(--accent-2);
      background: rgba(249, 247, 240, 0.86);
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-top: 28px;
    }}
    .section-head h2 {{ margin: 0 0 12px; }}
    .section-title {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .section-dot {{
      display: inline-block;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--accent);
    }}
    .section-dot.cat-proposal {{ background: var(--proposal); }}
    .section-dot.cat-education {{ background: var(--education); }}
    .section-dot.cat-visa {{ background: var(--visa); }}
    .section-dot.cat-other {{ background: var(--other); }}
    .count {{ color: var(--muted); font-size: 13px; }}
    .empty {{ color: var(--muted); background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    footer {{ color: var(--muted); font-size: 13px; margin-top: 34px; }}
    @media (max-width: 720px) {{
      header {{
        position: static;
        padding: 24px 16px calc(min(52vw, 240px) + 64px);
        background:
          linear-gradient(rgba(249, 247, 240, 0.30), rgba(249, 247, 240, 0.42)),
          url("images/nihongogogogo4.png") bottom center / contain no-repeat,
          var(--header);
      }}
      main {{ width: calc(100% - 24px); }}
      .top {{ width: calc(100% - 24px); }}
      .stats {{ grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }}
      .stat {{ padding: 6px 4px; font-size: 12px; line-height: 1.35; text-align: center; }}
      .stat strong {{ font-size: 25px; margin-bottom: 2px; }}
      .controls {{ grid-template-columns: 1fr; }}
      .search {{ height: 44px; font-size: 16px; }}
      .filters {{ justify-content: flex-start; }}
      .filter {{ min-height: 40px; padding: 0 14px; font-size: 14px; }}
      .grid {{ grid-template-columns: 1fr; }}
      article {{ padding: 15px; }}
      .title {{ font-size: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="top">
      <h1>日本語教育<br>資金・政策ウォッチ</h1>
      <p class="meta">最終更新: {escape(now.strftime("%Y-%m-%d %H:%M:%S %Z"))} / 対象期間: 直近{since_days}日</p>
      <div class="stats">
        <div class="stat"><strong>{len(visible_items)}</strong>表示件数</div>
        <div class="stat"><strong>{len(grouped.get("公募・補助金・プロポーザル", []))}</strong>公募・補助金</div>
        <div class="stat"><strong>{len(reflected_today)}</strong>本日反映</div>
        <div class="stat"><strong>{len(with_deadlines)}</strong>締切検出</div>
        <div class="stat"><strong>{len(urgent_items)}</strong>締切30日以内</div>
        <div class="stat"><strong>{len(recently_expired_items)}</strong>終了直後</div>
      </div>
      <div class="controls">
        <input class="search" id="search" type="search" placeholder="キーワード、自治体名、制度名で検索">
        <div class="filters" aria-label="表示フィルター">
          <button class="filter active" data-filter="all">すべて</button>
          <button class="filter" data-filter="deadline">締切あり</button>
          <button class="filter" data-filter="urgent">締切30日以内</button>
          <button class="filter" data-filter="expired">終了案件</button>
          <button class="filter" data-filter="公募・補助金・プロポーザル">公募</button>
          <button class="filter" data-filter="ニュース（日本語教育）">日本語教育</button>
          <button class="filter" data-filter="ニュース（外国人・ビザ）">外国人・ビザ</button>
          <button class="filter" data-filter="その他">その他</button>
        </div>
      </div>
    </div>
  </header>
  <main>
    {''.join(render_section(config, title, section_items, related_map) for title, section_items in sections if section_items)}
    <footer>
      <p>Semiosis株式会社 / Nihongo Catch! の販促・運用資金探索用に自動生成。</p>
    </footer>
  </main>
  <script>
    const search = document.querySelector("#search");
    const filters = Array.from(document.querySelectorAll(".filter"));
    const cards = Array.from(document.querySelectorAll("article[data-text]"));
    let activeFilter = "all";

    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      for (const card of cards) {{
        const textMatch = !query || card.dataset.text.includes(query);
        const filterMatch =
          activeFilter === "all" ||
          card.dataset.category === activeFilter ||
          (activeFilter === "deadline" && card.dataset.deadline === "true") ||
          (activeFilter === "urgent" && card.dataset.urgent === "true") ||
          (activeFilter === "expired" && card.dataset.expired === "true");
        const defaultHidden = card.dataset.expiredOld === "true" && activeFilter !== "expired";
        card.hidden = !(textMatch && filterMatch) || defaultHidden;
      }}
    }}

    search.addEventListener("input", applyFilters);
    for (const button of filters) {{
      button.addEventListener("click", () => {{
        activeFilter = button.dataset.filter;
        filters.forEach((item) => item.classList.toggle("active", item === button));
        applyFilters();
      }});
    }}
  </script>
</body>
</html>
"""


def render_section(
    config: WatchConfig,
    title: str,
    items: list[StoredItem],
    related_map: dict[int, list[StoredItem]] | None = None,
) -> str:
    category_class = category_class_for(title)
    return (
        f'<div class="section-head"><h2 class="section-title">'
        f'<span class="section-dot {category_class}"></span>{escape(title)}</h2>'
        f'<span class="count">{len(items)}件</span></div>\n'
        f"{render_cards(config, items[:30], related_map=related_map)}"
    )


def render_cards(
    config: WatchConfig,
    items: list[StoredItem],
    *,
    priority: bool = False,
    related_map: dict[int, list[StoredItem]] | None = None,
) -> str:
    if not items:
        return '<div class="empty">該当候補はまだありません。</div>'
    related_map = related_map or {}
    cards = "\n".join(
        render_card(config, item, priority=priority, related=related_map.get(item.id, []))
        for item in items
    )
    class_name = "grid" if priority else "list"
    return f'<div class="{class_name}">{cards}</div>'


def render_card(
    config: WatchConfig,
    item: StoredItem,
    *,
    priority: bool = False,
    related: list[StoredItem] | None = None,
) -> str:
    keywords = "".join(
        f'<span class="tag">{escape(keyword)}</span>'
        for keyword in item.matched_keywords[:8]
    )
    angle = config.sales_angles.get(item.primary_category, "")
    raw_summary = item.summary
    # 旧データはGoogle Newsのdescription（タイトルの焼き直し）がsummaryに入っている。
    # 情報ゼロの繰り返しは表示しない。
    if raw_summary and item.title[:24] and raw_summary.startswith(item.title[:24]):
        raw_summary = ""
    summary = truncate(raw_summary, 180)
    related_html = render_related(related or [])
    country_badge = f'<span class="badge country">{escape(item.country)}</span>' if item.country else ""
    deadline = parse_iso_date(item.deadline_at)
    remaining = days_until(deadline)
    is_urgent = remaining is not None and 0 <= remaining <= 30
    is_recent_expired = remaining is not None and -RECENTLY_EXPIRED_DAYS <= remaining < 0
    is_old_expired = remaining is not None and remaining < -RECENTLY_EXPIRED_DAYS
    category_class = category_class_for(item.primary_category)
    class_names = [
        category_class,
        "urgent" if is_urgent else "",
        "expired-recent" if is_recent_expired else "",
        "expired-old" if is_old_expired else "",
    ]
    if remaining is not None and remaining < 0:
        class_names.append("expired")
    class_name = " ".join(name for name in class_names if name)
    deadline_badge = render_deadline_badge(deadline, remaining)
    text = " ".join(
        [
            item.title,
            item.source_name,
            item.country,
            item.primary_category,
            item.summary,
            " ".join(item.matched_keywords),
        ]
    ).lower()
    return f"""
<article class="{class_name}" data-category="{escape(item.primary_category)}" data-deadline="{str(bool(deadline)).lower()}" data-urgent="{str(is_urgent).lower()}" data-expired="{str(remaining is not None and remaining < 0).lower()}" data-expired-old="{str(is_old_expired).lower()}" data-text="{escape(text)}"{" hidden" if is_old_expired else ""}>
  <p class="title"><a href="{escape(safe_url(item.url))}" target="_blank" rel="noopener noreferrer">{escape(item.title)}</a></p>
  <div class="row">
    <span class="badge {category_class}">{escape(item.primary_category)}</span>
    {country_badge}
    <span class="badge">スコア {item.score}</span>
    {deadline_badge}
  </div>
  <p class="item-meta">出典: {escape(item.source_name)} / 公開日: {escape(format_date(item.published_at))} / ページ反映日: {escape(format_date(item.fetched_at))}</p>
  <div>{keywords}</div>
  {f'<p class="summary">{linkify_html(summary)}</p>' if summary else ''}
  {related_html}
  <p class="summary">次アクション: {escape(next_action_for(item, remaining))}</p>
  {f'<p class="angle">Nihongo Catch! 提案切り口: {escape(angle)}</p>' if angle else ''}
</article>
"""


def truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else value[: max_length - 1] + "…"


def render_related(related: list[StoredItem]) -> str:
    """束ねた同一ニュースの他媒体報道を参照リンクとして残す（情報を消さない重複排除）。"""
    if not related:
        return ""
    links = "、".join(
        f'<a href="{escape(safe_url(item.url))}" target="_blank" rel="noopener noreferrer">'
        f"{escape(truncate(item.title, 28))}</a>"
        for item in related[:3]
    )
    more = f" ほか{len(related) - 3}件" if len(related) > 3 else ""
    return f'<p class="related">関連報道: {links}{more}</p>'


def safe_url(url: str) -> str:
    """Only allow http(s) links in hrefs; neutralize other schemes (javascript:, data:, ...)."""
    return url if url.lower().startswith(("https://", "http://")) else "#"


def linkify_html(value: str) -> str:
    escaped = escape(value)
    return re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )


def render_deadline_badge(deadline: date | None, remaining: int | None) -> str:
    if not deadline:
        return '<span class="badge">締切未検出</span>'
    if remaining is None:
        return f'<span class="badge deadline">締切 {deadline.isoformat()}</span>'
    if remaining < 0:
        elapsed = abs(remaining)
        if elapsed <= RECENTLY_EXPIRED_DAYS:
            return f'<span class="badge expired-recent">終了直後 {deadline.isoformat()} {elapsed}日前</span>'
        return f'<span class="badge expired">終了案件 {deadline.isoformat()} {elapsed}日前</span>'
    if remaining <= 14:
        return f'<span class="badge urgent">締切 {deadline.isoformat()} あと{remaining}日</span>'
    if remaining <= 30:
        return f'<span class="badge soon">締切 {deadline.isoformat()} あと{remaining}日</span>'
    return f'<span class="badge deadline">締切 {deadline.isoformat()} あと{remaining}日</span>'


def format_date(value: str | None) -> str:
    if not value:
        return "日付不明"
    try:
        return datetime.fromisoformat(value).astimezone(JST).strftime("%Y-%m-%d")
    except ValueError:
        return value


def next_action_for(item: StoredItem, remaining: int | None) -> str:
    if remaining is not None and remaining < -RECENTLY_EXPIRED_DAYS:
        return "通常一覧からは外し、次年度や類似公募の参考情報として保管"
    if remaining is not None and remaining < 0:
        return "過去案件として類似公募の条件、金額、提出書類を確認"
    if remaining is not None and remaining <= 30:
        return "公募要領、応募資格、対象経費、提出書類、共同提案可否を確認"
    if item.primary_category == "公募・補助金・プロポーザル":
        return "対象者、予算規模、Nihongo Catch! の提案余地を確認"
    if item.primary_category == "ニュース（外国人・ビザ）":
        return "制度変更が学校・受入機関の日本語教育ニーズに与える影響を確認"
    if item.primary_category == "ニュース（日本語教育）":
        return "認定校、登録日本語教員、Can Do評価との接点を確認"
    return "営業先候補、担当部署、導入打診の切り口を確認"


def category_class_for(category: str) -> str:
    return {
        "公募・補助金・プロポーザル": "cat-proposal",
        "ニュース（日本語教育）": "cat-education",
        "ニュース（外国人・ビザ）": "cat-visa",
        "その他": "cat-other",
    }.get(category, "cat-other")


def is_expired(item: StoredItem, *, today: date) -> bool:
    remaining = days_until(parse_iso_date(item.deadline_at), today=today)
    return remaining is not None and remaining < 0


def is_recently_expired(item: StoredItem, *, today: date) -> bool:
    remaining = days_until(parse_iso_date(item.deadline_at), today=today)
    return remaining is not None and -RECENTLY_EXPIRED_DAYS <= remaining < 0


def is_archived(item: StoredItem, *, today: date) -> bool:
    remaining = days_until(parse_iso_date(item.deadline_at), today=today)
    return remaining is not None and remaining < -ARCHIVE_AFTER_DAYS
