"""
БЕСПЛАТНАЯ версия: ежедневная сводка новостей об экономике Узбекистана
из зарубежных СМИ — без платного Anthropic API.

Как это работает:
- Скрипт читает RSS-ленты нескольких зарубежных изданий/агентств
- Для лент, посвящённых конкретно Узбекистану (RFE/RL), фильтрует
  только по экономическим ключевым словам
- Для общих региональных лент требует совпадение и по стране,
  и по экономическому термину
- Формирует список заголовков со ссылками, без пересказа
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
        "name": "Times of Central Asia — Узбекистан",
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


def format_digest(items: list[dict]) -> str:
    if not items:
        return (
            f"За последние {HOURS_LOOKBACK} ч. не найдено новостей об "
            "экономике Узбекистана в отслеживаемых зарубежных источниках."
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
