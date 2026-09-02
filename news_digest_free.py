"""
БЕСПЛАТНАЯ версия: ежедневная сводка новостей об экономике Узбекистана
из зарубежных СМИ — без платного Anthropic API.

Как это работает:
- Скрипт читает RSS-ленты нескольких зарубежных изданий/агентств
- Для лент, посвящённых конкретно Узбекистану (RFE/RL, Eurasianet),
  фильтрует только по экономическим ключевым словам
- Для общих региональных лент требует совпадение и по стране,
  и по экономическому термину
- Формирует один HTML-файл со списком ссылок, сгруппированных по источнику
- Отправляет этот файл в Telegram как вложение (документ)

Ничего не стоит: RSS-ленты бесплатны, Telegram Bot API бесплатен,
GitHub Actions бесплатен (в пределах щедрого лимита минут в месяц).
"""

import os
import sys
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- Зарубежные RSS-ленты ---
# already_country_specific=True — лента и так посвящена Узбекистану,
# дополнительно искать слово "Узбекистан" в тексте не нужно, хватит
# экономического ключевого слова.
FEEDS = [
    {
        "name": "RFE/RL — Узбекистан (Радио Озодлик)",
        "url": "https://www.rferl.org/api/ztiiml-vomx-tpekgm_",
        "already_country_specific": True,
    },
    {
        "name": "Eurasianet — Узбекистан",
        "url": "https://eurasianet.org/region/uzbekistan/feed",
        "already_country_specific": True,
    },
    {
        "name": "Times of Central Asia",
        "url": "https://timesca.com/feed",
        "already_country_specific": False,
    },
    {
        "name": "The Diplomat",
        "url": "https://thediplomat.com/feed/",
        "already_country_specific": False,
    },
    {
        "name": "AKIpress",
        "url": "https://akipress.com/rss/news.rss",
        "already_country_specific": False,
    },
    {
        "name": "Silk Road Briefing",
        "url": "https://www.silkroadbriefing.com/news/feed/",
        "already_country_specific": False,
    },
]

# --- Ключевые слова для фильтрации (регистр не важен) ---
COUNTRY_KEYWORDS = ["uzbekistan", "узбекистан", "tashkent", "ташкент", "uzbek"]
ECONOMY_KEYWORDS = [
    "econom", "экономик", "gdp", "ввп", "inflation", "инфляц",
    "trade", "торгов", "investment", "инвестиц", "export", "экспорт",
    "import", "импорт", "bank", "банк", "currency", "валют", "sum ",
    "budget", "бюджет", "finance", "финанс", "market", "рынок",
    "reform", "реформ", "industry", "промышленн", "energy", "энергет",
    "gas", "газ", "oil", "нефт", "cotton", "хлопок", "gold", "золот",
    "loan", "кредит", "debt", "долг", "tax", "налог", "privatiz",
    "приватизац", "IMF", "МВФ", "World Bank", "Всемирный банк",
    "growth", "рост экономики", "price", "цен",
]

HOURS_LOOKBACK = 168  # 7 дней — чтобы не пропускать новости из редко обновляемых лент


def matches_filters(title: str, summary: str, already_country_specific: bool) -> bool:
    text = f"{title} {summary}".lower()
    has_economy = any(kw.lower() in text for kw in ECONOMY_KEYWORDS)
    if already_country_specific:
        return has_economy
    has_country = any(kw in text for kw in COUNTRY_KEYWORDS)
    return has_country and has_economy


def entry_is_recent(entry) -> bool:
    time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not time_struct:
        return True  # если дата не указана, не отбрасываем — лучше показать
    published = datetime(*time_struct[:6], tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    return published >= cutoff


def clean_html(raw: str) -> str:
    return re.sub("<[^<]+?>", "", raw or "").strip()


def collect_news() -> list[dict]:
    results = []
    seen_links = set()

    for feed_cfg in FEEDS:
        source_name = feed_cfg["name"]
        url = feed_cfg["url"]
        already_country_specific = feed_cfg["already_country_specific"]

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Не удалось загрузить {source_name}: {e}", file=sys.stderr)
            continue

        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"Лента {source_name} не вернула записей (bozo={feed.bozo})", file=sys.stderr)

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            if not link or link in seen_links:
                continue
            if not matches_filters(title, summary, already_country_specific):
                continue
            if not entry_is_recent(entry):
                continue

            seen_links.add(link)
            results.append({
                "source": source_name,
                "title": title,
                "link": link,
            })

    return results


def build_html_file(items: list[dict]) -> str:
    today_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    grouped = defaultdict(list)
    for item in items:
        grouped[item["source"]].append(item)

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='ru'>",
        "<head>",
        "<meta charset='utf-8'>",
        f"<title>Экономика Узбекистана — {today_str}</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 0 16px; color: #222; }",
        "h1 { font-size: 20px; border-bottom: 2px solid #00244E; padding-bottom: 8px; }",
        "h2 { font-size: 16px; color: #00244E; margin-top: 28px; }",
        "ul { padding-left: 20px; }",
        "li { margin-bottom: 10px; line-height: 1.4; }",
        "a { color: #0645AD; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        ".empty { color: #666; font-style: italic; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>Экономика Узбекистана — новости из зарубежных СМИ ({today_str})</h1>",
    ]

    if not items:
        html_parts.append(
            f"<p class='empty'>За последние {HOURS_LOOKBACK} ч. не найдено новостей "
            "об экономике Узбекистана в отслеживаемых зарубежных источниках.</p>"
        )
    else:
        for source_name, source_items in grouped.items():
            html_parts.append(f"<h2>{source_name}</h2>")
            html_parts.append("<ul>")
            for item in source_items:
                html_parts.append(
                    f"<li><a href='{item['link']}'>{item['title']}</a></li>"
                )
            html_parts.append("</ul>")

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
