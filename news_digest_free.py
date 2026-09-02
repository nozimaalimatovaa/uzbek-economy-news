"""
БЕСПЛАТНАЯ версия: ежедневная сводка новостей об экономике Узбекистана
из зарубежных СМИ — без платного Anthropic API.

Как это работает:
- Скрипт запрашивает Google News RSS (поиск по ключевым словам) —
  это бесплатный агрегатор, который сам собирает статьи с десятков
  зарубежных изданий по заданному запросу
- Результаты с доменами .uz (местные узбекские сайты) отфильтровываются,
  остаются только зарубежные источники
- Если с первого запроса набралось меньше 7 новостей, период поиска
  автоматически расширяется, чтобы гарантированно набрать 7-10 новостей
- Формируется один HTML-файл со списком ссылок
- Файл отправляется в Telegram как вложение (документ)

Ничего не стоит: Google News RSS бесплатен без ключей и регистрации,
Telegram Bot API бесплатен, GitHub Actions бесплатен.
"""

import os
import sys
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- Поисковые запросы к Google News (широкий охват тем, чтобы за 2 дня
#     гарантированно набиралось 7-10 новостей) ---
SEARCH_QUERIES = [
    ("Uzbekistan economy", "en"),
    ("Uzbekistan investment", "en"),
    ("Uzbekistan trade", "en"),
    ("Uzbekistan GDP", "en"),
    ("Uzbekistan currency", "en"),
    ("Uzbekistan banking", "en"),
    ("Uzbekistan export", "en"),
    ("Uzbekistan IMF", "en"),
    ("Uzbekistan finance minister", "en"),
    ("Tashkent stock exchange", "en"),
    ("Узбекистан экономика", "ru"),
    ("Узбекистан инвестиции", "ru"),
    ("Узбекистан торговля", "ru"),
    ("Узбекистан валюта", "ru"),
    ("Узбекистан бюджет", "ru"),
]

# Локальные домены Узбекистана, которые исключаем (нужны только зарубежные)
LOCAL_DOMAINS_TO_EXCLUDE = [".uz"]

MIN_ITEMS = 7
MAX_ITEMS = 10

# Фиксированный период поиска — 2 дня. Если вдруг совсем не наберётся
# MIN_ITEMS, скрипт один раз подстрахуется и заглянет на 4 дня назад,
# но это резервный вариант, а не обычный режим работы.
LOOKBACK_STAGES_DAYS = [2, 4]


def google_news_rss_url(query: str, lang: str, days: int) -> str:
    # "when:Xd" — встроенный фильтр Google News по давности публикации
    q = f"{query} when:{days}d"
    encoded_q = quote(q)
    if lang == "ru":
        return f"https://news.google.com/rss/search?q={encoded_q}&hl=ru&gl=UZ&ceid=UZ:ru"
    return f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"


def is_local_domain(link: str) -> bool:
    try:
        host = urlparse(link).netloc.lower()
    except Exception:
        return False
    return any(host.endswith(d) for d in LOCAL_DOMAINS_TO_EXCLUDE)


def extract_source_name(entry, link: str) -> str:
    # У Google News записи часто есть entry.source.title
    source = entry.get("source")
    if source and isinstance(source, dict) and source.get("title"):
        return source["title"]
    try:
        return urlparse(link).netloc.replace("www.", "")
    except Exception:
        return "Источник"


def fetch_for_days(days: int) -> list[dict]:
    results = []
    seen_links = set()

    for query, lang in SEARCH_QUERIES:
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
            if is_local_domain(link):
                continue

            seen_links.add(link)
            results.append({
                "source": extract_source_name(entry, link),
                "title": title,
                "link": link,
                "published": entry.get("published_parsed"),
            })

    # Сортировка по дате публикации (новые сверху), записи без даты — в конец
    results.sort(
        key=lambda x: x["published"] if x["published"] else (0,) * 9,
        reverse=True,
    )
    return results


def collect_news() -> list[dict]:
    for days in LOOKBACK_STAGES_DAYS:
        items = fetch_for_days(days)
        if len(items) >= MIN_ITEMS:
            return items[:MAX_ITEMS]
    # Если даже за 30 дней набралось меньше MIN_ITEMS — возвращаем что есть
    return items[:MAX_ITEMS]


def build_html_file(items: list[dict]) -> str:
    today_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='ru'>",
        "<head>",
        "<meta charset='utf-8'>",
        f"<title>Экономика Узбекистана — {today_str}</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 0 16px; color: #222; }",
        "h1 { font-size: 20px; border-bottom: 2px solid #00244E; padding-bottom: 8px; }",
        "ol { padding-left: 20px; }",
        "li { margin-bottom: 14px; line-height: 1.4; }",
        "a { color: #0645AD; text-decoration: none; font-weight: 600; }",
        "a:hover { text-decoration: underline; }",
        ".source { color: #666; font-size: 13px; }",
        ".empty { color: #666; font-style: italic; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>Экономика Узбекистана — новости из зарубежных СМИ ({today_str})</h1>",
    ]

    if not items:
        html_parts.append(
            "<p class='empty'>Не удалось найти новости об экономике Узбекистана "
            "в зарубежных источниках за отслеживаемый период.</p>"
        )
    else:
        html_parts.append("<ol>")
        for item in items:
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
