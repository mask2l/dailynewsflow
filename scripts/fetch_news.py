#!/usr/bin/env python3
"""NewsFlow - Minimal News Aggregator
Fetches RSS feeds concurrently, generates a static HTML page.
"""

import feedparser
import yaml
import os
import re
import hashlib
import ssl
import random
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment, FileSystemLoader
from email.utils import parsedate_to_datetime
import requests

ssl._create_default_https_context = ssl._create_unverified_context

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(PROJECT_DIR, "feeds.yaml")
TEMPLATE_DIR = os.path.join(PROJECT_DIR, "templates")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")

MAX_ENTRIES_PER_SOURCE = 10
MAX_TOTAL_ENTRIES = 500
MAX_TRANSLATE_ENTRIES = 10  # Only translate top 10 entries (10*50*3*30=45k chars/month, within 50k limit)
MAX_WORKERS = 30
USER_AGENT = "Mozilla/5.0 (compatible; NewsFlow/1.0; +https://github.com)"

BAIDU_APPID = os.getenv("BAIDU_APPID", "20260528002621795")
BAIDU_SECRET_KEY = os.getenv("BAIDU_SECRET_KEY", "ldoyoxdwT1NqE77_spQ1")
BAIDU_API_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_entry_date(entry):
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for field in ("published", "updated"):
        date_str = entry.get(field)
        if date_str:
            try:
                return parsedate_to_datetime(date_str).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_favicon(url):
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
    except Exception:
        return ""


def translate_baidu(text, from_lang="en", to_lang="zh"):
    """Translate text using Baidu Translate API."""
    if not text or len(text) < 2:
        return text
    try:
        salt = str(random.randint(32768, 65536))
        sign_str = BAIDU_APPID + text + salt + BAIDU_SECRET_KEY
        sign = hashlib.md5(sign_str.encode()).hexdigest()
        params = {
            "q": text,
            "from": from_lang,
            "to": to_lang,
            "appid": BAIDU_APPID,
            "salt": salt,
            "sign": sign,
        }
        resp = requests.get(BAIDU_API_URL, params=params, timeout=10)
        result = resp.json()
        if "trans_result" in result:
            return result["trans_result"][0]["dst"]
        else:
            print(f"  [WARN] Translation failed: {result.get('error_msg', 'unknown')}")
            return text
    except Exception as e:
        print(f"  [WARN] Translation error: {e}")
        return text


def is_english(text):
    """Check if text is primarily English."""
    if not text:
        return False
    english_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    total_chars = sum(1 for c in text if c.isalpha())
    return total_chars > 0 and english_chars / total_chars > 0.6


def fetch_feed(source, category_name):
    entries = []
    rss_url = source.get("rss", "")
    if not rss_url:
        return entries
    try:
        feed = feedparser.parse(
            rss_url,
            request_headers={"User-Agent": USER_AGENT},
        )
        if feed.bozo and not feed.entries:
            print(f"  [WARN] {source['name']}: {getattr(feed, 'bozo_exception', 'unknown')}")
            return entries

        source_url = source.get("url", "")
        for entry in feed.entries[:MAX_ENTRIES_PER_SOURCE]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            pub_date = parse_entry_date(entry)
            summary = strip_html(entry.get("summary", ""))
            if len(summary) > 200:
                summary = summary[:200] + "..."

            entries.append({
                "title": title,
                "link": link,
                "published": pub_date,
                "published_ts": pub_date.timestamp(),
                "summary": summary,
                "source_name": source["name"],
                "source_url": source_url,
                "source_icon": get_favicon(source_url),
                "category": category_name,
                "id": hashlib.md5(link.encode()).hexdigest()[:12],
            })
        print(f"  [OK] {source['name']}: {len(entries)} entries")
    except Exception as e:
        print(f"  [ERR] {source['name']}: {e}")
    return entries


def format_time_ago(dt):
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = (now - dt).total_seconds()
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds / 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds / 3600)} 小时前"
    if seconds < 604800:
        return f"{int(seconds / 86400)} 天前"
    return dt.strftime("%m-%d")


def main():
    print("=" * 50)
    print("NewsFlow - Fetching feeds...")
    print("=" * 50)

    config = load_config()
    all_entries = []
    category_names = []
    sources_with_category = []

    for category in config["categories"]:
        cat_name = category["name"]
        category_names.append(cat_name)
        for source in category["sources"]:
            sources_with_category.append((source, cat_name))

    total_sources = len(sources_with_category)
    print(f"\nFetching {total_sources} sources across {len(category_names)} categories...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_feed, src, cat): (src, cat)
            for src, cat in sources_with_category
        }
        for future in as_completed(futures):
            try:
                all_entries.extend(future.result())
            except Exception as e:
                src, cat = futures[future]
                print(f"  [ERR] {src['name']}: {e}")

    # Deduplicate by link
    seen = set()
    unique = []
    for entry in all_entries:
        if entry["link"] not in seen:
            seen.add(entry["link"])
            unique.append(entry)
    all_entries = unique

    # Sort newest first, then limit
    all_entries.sort(key=lambda x: x["published_ts"], reverse=True)
    all_entries = all_entries[:MAX_TOTAL_ENTRIES]

    # Translate top entries (save quota)
    print(f"\nTranslating top {MAX_TRANSLATE_ENTRIES} English titles...")
    for i, entry in enumerate(all_entries[:MAX_TRANSLATE_ENTRIES]):
        if is_english(entry["title"]):
            translated = translate_baidu(entry["title"])
            entry["title"] = translated
            entry["original_title"] = entry.get("original_title", entry["title"])
            time.sleep(1)  # Rate limit: Baidu free tier QPS=1
            print(f"  [{i+1}/{MAX_TRANSLATE_ENTRIES}] {entry['original_title'][:50]}... → {translated[:50]}...")

    for entry in all_entries:
        entry["time_ago"] = format_time_ago(entry["published"])
        entry["date_str"] = entry["published"].strftime("%Y-%m-%d %H:%M")

    category_counts = {}
    for entry in all_entries:
        category_counts[entry["category"]] = category_counts.get(entry["category"], 0) + 1

    successful_sources = len({e["source_name"] for e in all_entries})

    # Render
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("index.html")

    cst = timezone(timedelta(hours=8))
    html = template.render(
        entries=all_entries,
        categories=category_names,
        category_counts=category_counts,
        total_sources=total_sources,
        successful_sources=successful_sources,
        total_entries=len(all_entries),
        updated_at=datetime.now(cst).strftime("%Y-%m-%d %H:%M CST"),
    )

    output_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{'=' * 50}")
    print(f"Done! {len(all_entries)} entries from {successful_sources}/{total_sources} sources")
    print(f"Output: {output_path}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
