"""
БЕСПЛАТНАЯ версия: ежедневная сводка новостей об экономике Узбекистана
из зарубежных СМИ и международных организаций — без платного Anthropic API.

Как это работает:
- Скрипт запрашивает Google News RSS (поиск по ключевым словам) —
  это бесплатный агрегатор, который сам собирает статьи с десятков
  зарубежных изданий по заданному запросу
- Отдельно добавлены прицельные запросы по сайтам конкретных
  международных организаций (World Bank, ADB, IMF, EBRD, UN и др.)
  через оператор site: в Google News
- Результаты с доменами .uz (местные узбекские сайты) отфильтровываются,
  остаются только зарубежные источники
- Формируется один HTML-файл со списком ссылок
- Файл отправляется в Telegram как вложение (документ)

Ничего не стоит: Google News RSS бесплатен без ключей и регистрации,
Telegram Bot API бесплатен, GitHub Actions бесплатен.
"""

import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Каждый запрос — (текст запроса, язык, категория для группировки в сводке)
CAT_GENERAL = "Экономика и финансы Узбекистана"
CAT_REGION = "Центральная Азия"
CAT_ORG = "Международные организации"
CAT_PRESS = "Деловые издания и рейтинговые агентства"

# --- Общие поисковые запросы к Google News (широкий охват тем) ---
GENERAL_QUERIES = [
    ("Uzbekistan economy", "en", CAT_GENERAL),
    ("Uzbekistan investment", "en", CAT_GENERAL),
    ("Uzbekistan trade", "en", CAT_GENERAL),
    ("Uzbekistan GDP", "en", CAT_GENERAL),
    ("Uzbekistan currency", "en", CAT_GENERAL),
    ("Uzbekistan banking", "en", CAT_GENERAL),
    ("Uzbekistan export", "en", CAT_GENERAL),
    ("Uzbekistan IMF", "en", CAT_GENERAL),
    ("Uzbekistan finance minister", "en", CAT_GENERAL),
    ("Tashkent stock exchange", "en", CAT_GENERAL),
    ("Uzbekistan World Bank", "en", CAT_GENERAL),
    ("Uzbekistan Asian Development Bank", "en", CAT_GENERAL),
    ("Uzbekistan EBRD", "en", CAT_GENERAL),
    ("Uzbekistan sovereign bond", "en", CAT_GENERAL),
    ("Uzbekistan privatization", "en", CAT_GENERAL),
    ("Uzbekistan credit rating", "en", CAT_GENERAL),
    ("Uzbekistan Moody's", "en", CAT_GENERAL),
    ("Uzbekistan S&P Global", "en", CAT_GENERAL),
    ("Uzbekistan Fitch Ratings", "en", CAT_GENERAL),
    ("Uzbekistan agriculture export", "en", CAT_GENERAL),
    ("Uzbekistan textile industry", "en", CAT_GENERAL),
    ("Uzbekistan mining minerals", "en", CAT_GENERAL),
    ("Uzbekistan gold reserves", "en", CAT_GENERAL),
    ("Uzbekistan tourism revenue", "en", CAT_GENERAL),
    ("Uzbekistan free economic zone", "en", CAT_GENERAL),
    ("Uzbekistan WTO accession", "en", CAT_GENERAL),
    ("Uzbekistan customs tariff", "en", CAT_GENERAL),
    ("Uzbekistan remittances", "en", CAT_GENERAL),
    ("Uzbekistan labor market employment", "en", CAT_GENERAL),
    ("Uzbekistan digital economy fintech", "en", CAT_GENERAL),
    ("Uzbekistan real estate market", "en", CAT_GENERAL),
    ("Uzbekistan energy sector reform", "en", CAT_GENERAL),
    ("Uzbekistan renewable energy solar", "en", CAT_GENERAL),
    ("Uzbekistan railway infrastructure", "en", CAT_GENERAL),
    ("Uzbekistan foreign direct investment", "en", CAT_GENERAL),
    ("Uzbekistan central bank interest rate", "en", CAT_GENERAL),
    ("Uzbekistan inflation rate", "en", CAT_GENERAL),
    ("Uzbekistan state budget deficit", "en", CAT_GENERAL),
    ("Uzbekistan IPO", "en", CAT_GENERAL),
    ("Узбекистан экономика", "ru", CAT_GENERAL),
    ("Узбекистан инвестиции", "ru", CAT_GENERAL),
    ("Узбекистан торговля", "ru", CAT_GENERAL),
    ("Узбекистан валюта", "ru", CAT_GENERAL),
    ("Узбекистан бюджет", "ru", CAT_GENERAL),
    ("Узбекистан кредитный рейтинг", "ru", CAT_GENERAL),
    ("Узбекистан промышленность", "ru", CAT_GENERAL),
    ("Узбекистан сельское хозяйство экспорт", "ru", CAT_GENERAL),
    ("Узбекистан туризм", "ru", CAT_GENERAL),
    ("Узбекистан центральный банк ставка", "ru", CAT_GENERAL),
    ("Узбекистан инфляция", "ru", CAT_GENERAL),
    ("Узбекистан IPO биржа", "ru", CAT_GENERAL),
    ("Узбекистан иностранные инвестиции", "ru", CAT_GENERAL),
]

# --- Центральная Азия в целом (регион, где Узбекистан — часть контекста) ---
REGION_QUERIES = [
    ("Central Asia economy", "en", CAT_REGION),
    ("Central Asia investment", "en", CAT_REGION),
    ("Central Asia trade", "en", CAT_REGION),
    ("Central Asia energy", "en", CAT_REGION),
    ("Central Asia IMF", "en", CAT_REGION),
    ("Central Asia World Bank", "en", CAT_REGION),
    ("Central Asia China trade", "en", CAT_REGION),
    ("Центральная Азия экономика", "ru", CAT_REGION),
    ("Центральная Азия инвестиции", "ru", CAT_REGION),
    ("Центральная Азия торговля", "ru", CAT_REGION),
]

# --- Прицельные запросы по сайтам конкретных международных организаций ---
# Google News поддерживает оператор site: прямо в поисковой строке
ORG_SITES = [
    "worldbank.org",
    "adb.org",
    "imf.org",
    "ebrd.com",
    "unece.org",
    "undp.org",
    "eurasia.undp.org",
    "oecd.org",
]

ORG_QUERIES = [
    (f"Uzbekistan site:{site}", "en", CAT_ORG) for site in ORG_SITES
]

# --- Прицельный поиск по крупным зарубежным финансовым/деловым изданиям
#     и рейтинговым агентствам ---
NEWS_SITES = [
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "economist.com",
    "wsj.com",
    "spglobal.com",
    "moodys.com",
    "fitchratings.com",
    "cbonds.com",
]

NEWS_SITE_QUERIES = [
    (f"Uzbekistan site:{site}", "en", CAT_PRESS) for site in NEWS_SITES
]

SEARCH_QUERIES = GENERAL_QUERIES + REGION_QUERIES + ORG_QUERIES + NEWS_SITE_QUERIES

# Локальные домены Узбекистана, которые исключаем (нужны только зарубежные)
LOCAL_DOMAINS_TO_EXCLUDE = [".uz"]

# Названия источников, которые тоже считаем локальными (подстраховка,
# на случай если домен определить не удалось)
LOCAL_SOURCE_NAME_MARKERS = [
    ".uz", "uzbekistan today", "kun.uz", "gazeta.uz",
    "podrobno.uz", "spot.uz", "daryo.uz",
]

MIN_ITEMS = 7
MAX_ITEMS = 30  # сводка для министра — полнота важнее краткости

# Периоды поиска: основной — 2 дня; если совсем ничего не наберётся,
# один раз подстрахуемся и заглянем на 4 дня назад.
LOOKBACK_STAGES_DAYS = [2, 4]


def google_news_rss_url(query: str, lang: str, days: int) -> str:
    # "when:Xd" — встроенный фильтр Google News по давности публикации
    q = f"{query} when:{days}d"
    encoded_q = quote(q)
    if lang == "ru":
        return f"https://news.google.com/rss/search?q={encoded_q}&hl=ru&gl=UZ&ceid=UZ:ru"
    return f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"


def is_local_domain(entry, link: str) -> bool:
    # У Google News реальная ссылка на источник обычно в entry.source.href,
    # а entry.link — это редирект через news.google.com, поэтому домен
    # нужно проверять именно по source.href, если он есть.
    source = entry.get("source")
    candidate = link
    if source and isinstance(source, dict) and source.get("href"):
        candidate = source["href"]

    try:
        host = urlparse(candidate).netloc.lower()
    except Exception:
        return False
    return any(host.endswith(d) for d in LOCAL_DOMAINS_TO_EXCLUDE)


def extract_source_name(entry, link: str) -> str:
    # У Google News записи часто есть entry.source.title
    source = entry.get("source")
    if source and isinstance(source, dict) and source.get("title"):
        return source["title"]
    candidate = link
    if source and isinstance(source, dict) and source.get("href"):
        candidate = source["href"]
    try:
        return urlparse(candidate).netloc.replace("www.", "")
    except Exception:
        return "Источник"


def fetch_for_days(days: int) -> list[dict]:
    results = []
    seen_links = set()

    for query, lang, category in SEARCH_QUERIES:
        url = google_news_rss_url(query, lang, days)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Ошибка запроса '{query}' ({lang}): {e}", file=sys.stderr)
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")

            if not link or link in seen_links:
                continue
            if is_local_domain(entry, link):
                continue

            source_name = extract_source_name(entry, link)
            if any(marker in source_name.lower() for marker in LOCAL_SOURCE_NAME_MARKERS):
                continue

            seen_links.add(link)
            results.append({
                "source": source_name,
                "title": title,
                "link": link,
                "published": entry.get("published_parsed"),
                "category": category,
            })

    # Сортировка по дате публикации (новые сверху), записи без даты — в конец
    results.sort(
        key=lambda x: x["published"] if x["published"] else (0,) * 9,
        reverse=True,
    )
    return results


def collect_news() -> list[dict]:
    items = []
    for days in LOOKBACK_STAGES_DAYS:
        items = fetch_for_days(days)
        if len(items) >= MIN_ITEMS:
            break

    # Приоритет: все новости от международных организаций и деловых изданий
    # сохраняем целиком (их обычно немного, но они самые ценные для сводки),
    # а оставшееся место заполняем общими новостями по Узбекистану и региону.
    priority_categories = {CAT_ORG, CAT_PRESS}
    priority_items = [i for i in items if i["category"] in priority_categories]
    other_items = [i for i in items if i["category"] not in priority_categories]

    remaining_slots = max(MAX_ITEMS - len(priority_items), 0)
    return priority_items + other_items[:remaining_slots]


def build_html_file(items: list[dict]) -> str:
    today_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    # Группировка по категориям, порядок категорий фиксированный и осмысленный
    category_order = [CAT_ORG, CAT_PRESS, CAT_GENERAL, CAT_REGION]
    grouped: dict[str, list[dict]] = {cat: [] for cat in category_order}
    for item in items:
        grouped.setdefault(item.get("category", CAT_GENERAL), []).append(item)

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='ru'>",
        "<head>",
        "<meta charset='utf-8'>",
        f"<title>Экономика Узбекистана — {today_str}</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 0 16px; color: #222; }",
        "h1 { font-size: 20px; border-bottom: 2px solid #00244E; padding-bottom: 8px; }",
        "h2 { font-size: 16px; color: #00244E; margin-top: 26px; border-left: 4px solid #cfb082; padding-left: 8px; }",
        "ol { padding-left: 20px; }",
        "li { margin-bottom: 14px; line-height: 1.4; }",
        "a { color: #0645AD; text-decoration: none; font-weight: 600; }",
        "a:hover { text-decoration: underline; }",
        ".source { color: #666; font-size: 13px; }",
        ".empty { color: #666; font-style: italic; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>Экономика Узбекистана — новости из зарубежных СМИ и международных организаций ({today_str})</h1>",
    ]

    if not items:
        html_parts.append(
            "<p class='empty'>Не удалось найти новости об экономике Узбекистана "
            "в зарубежных источниках за отслеживаемый период.</p>"
        )
    else:
        for category in category_order:
            cat_items = grouped.get(category, [])
            if not cat_items:
                continue
            html_parts.append(f"<h2>{category}</h2>")
            html_parts.append("<ol>")
            for item in cat_items:
                html_parts.append(
                    "<li>"
                    f"<a href='{item['link']}'>{item['title']}</a><br>"
                    f"<span class='source'>{item['source']}</span>"
                    "</li>"
                )
            html_parts.append("</ol>")

    html_parts.append("</body></html>")

    file_path = "/tmp/uzbek_economy_digest.html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    return file_path


def send_file_to_telegram(file_path: str, caption: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"

    with open(file_path, "rb") as f:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"document": (os.path.basename(file_path), f, "text/html")},
            timeout=60,
        )

    if resp.status_code != 200:
        print(f"Ошибка отправки файла в Telegram: {resp.status_code} {resp.text}", file=sys.stderr)
        resp.raise_for_status()


def main():
    today_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    items = collect_news()
    file_path = build_html_file(items)
    caption = f"Экономика Узбекистана — сводка ссылок за {today_str} ({len(items)} новостей)"
    send_file_to_telegram(file_path, caption)
    print(f"Отправлен файл. Новостей: {len(items)}")


if __name__ == "__main__":
    main()
