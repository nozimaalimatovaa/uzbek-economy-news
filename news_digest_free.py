"""
БЕСПЛАТНАЯ версия: ежедневная сводка новостей об экономике Узбекистана
из зарубежных СМИ — без платного Anthropic API.

Как это работает:
- Скрипт читает RSS-ленты нескольких зарубежных изданий/агентств
- Отбирает только те новости, где встречаются ключевые слова
  (Узбекистан / Uzbekistan / Tashkent + экономические термины)
- Формирует список заголовков со ссылками
- Отправляет в Telegram

Ничего не стоит: RSS-ленты бесплатны, Telegram Bot API бесплатен,
GitHub Actions бесплатен (в пределах щедрого лимита минут в месяц).
"""

import os
import sys
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- Зарубежные RSS-ленты, где может встречаться экономика Узбекистана ---
FEEDS = {
    "RFE/RL (Радио Свобода)": "https://www.rferl.org/api/zrqiteuuir",  # общий feed RFE/RL
    "EurasiaNet": "https://eurasianet.org/rss",
    "The Diplomat": "https://thediplomat.com/feed/",
    "Reuters World News": "https://www.reutersagency.com/feed/?best-topics=world&post_type=best",
    "AKIpress": "https://akipress.com/rss/news.rss",
    "Trend News Agency": "https://en.trend.az/rss/",
}

# --- Ключевые слова для фильтрации (регистр не важен) ---
COUNTRY_KEYWORDS = ["uzbekistan", "узбекистан", "tashkent", "ташкент"]
ECONOMY_KEYWORDS = [
    "econom", "экономик", "gdp", "ввп", "inflation", "инфляц",
    "trade", "торгов", "investment", "инвестиц", "export", "экспорт",
    "import", "импорт", "bank", "банк", "currency", "валют",
    "budget", "бюджет", "finance", "финанс", "market", "рынок",
    "reform", "реформ", "industry", "промышленн",
]

HOURS_LOOKBACK = 48  # за сколько часов брать новости


def matches_filters(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    has_country = any(kw in text for kw in COUNTRY_KEYWORDS)
    has_economy = any(kw in text for kw in ECONOMY_KEYWORDS)
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
    for source_name, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Не удалось загрузить {source_name}: {e}", file=sys.stderr)
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            if not matches_filters(title, summary):
                continue
            if not entry_is_recent(entry):
                continue

            results.append({
                "source": source_name,
                "title": title,
                "link": link,
            })

    return results


def format_digest(items: list[dict]) -> str:
    if not items:
        return (
            "За последние сутки не найдено новостей об экономике "
            "Узбекистана в отслеживаемых зарубежных источниках."
        )

    lines = []
    for item in items:
        lines.append(f"{item['title']} — {item['link']}")

    return "\n\n".join(lines)


def send_to_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for chunk in chunks:
        resp = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"Ошибка отправки в Telegram: {resp.status_code} {resp.text}", file=sys.stderr)
            resp.raise_for_status()


def main():
    header = "Экономика Узбекистана — новости из зарубежных СМИ:\n\n"
    items = collect_news()
    digest = format_digest(items)
    send_to_telegram(header + digest)
    print(f"Отправлено новостей: {len(items)}")


if __name__ == "__main__":
    main()
