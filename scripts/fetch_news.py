#!/usr/bin/env python3
"""NewsFlow - Minimal News Aggregator with Analytics, SEO & Translation
Fetches RSS feeds concurrently, translates top English titles, performs trend analysis,
and generates static individual article pages for SEO.
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
ARTICLES_DIR = os.path.join(OUTPUT_DIR, "articles")

MAX_ENTRIES_PER_SOURCE = 10
MAX_TOTAL_ENTRIES = 500
ENABLE_BAIDU_TRANSLATE = False  # 暂停百度翻译：避免中英混合导致前端 translate.js 混乱，完全由 translate.js 100% 绿色接管
MAX_TRANSLATE_ENTRIES = 15 if ENABLE_BAIDU_TRANSLATE else 0  # Only translate top 10-15 entries to save quota
MAX_SEO_PAGES = 50          # Generate separate SEO HTML pages for top 50 articles
MAX_WORKERS = 30
USER_AGENT = "Mozilla/5.0 (compatible; NewsFlow/1.0; +https://github.com)"

BAIDU_APPID = os.getenv("BAIDU_APPID", "20260528002621795")
BAIDU_SECRET_KEY = os.getenv("BAIDU_SECRET_KEY", "ldoyoxdwT1NqE77_spQ1")
BAIDU_API_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"

# Simple stop words lists for analysis
STOP_WORDS = {
    'the', 'of', 'and', 'to', 'in', 'a', 'is', 'for', 'on', 'with', 'as', 'at', 'by', 'an', 'it', 'from', 'that', 'this', 'are', 'be',
    'the', 'how', 'what', 'why', 'who', 'where', 'which', 'your', 'my', 'their', 'our', 'his', 'her', 'its', 'their', 'not', 'no', 'yes',
    '的', '了', '在', '是', '我', '有', '和', '人', '这', '中', '大', '来', '上', '国', '个', '到', '说', '要', '于', '以', '等', '为', '之', '也',
    '下', '自', '自个', '你', '他', '她', '它', '我们', '你们', '他们', '这个', '那个', '有些', '一些', '如何', '什么', '为什么', '哪个', '你的', '我的',
    '的', '地', '得', '着', '过', '被', '把', '让', '使', '让', '叫', '去', '回', '开', '出', '进', '起', '落', '拿', '抱', '抓', '放', '丢', '扔'
}


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


def assign_hot_tag(entry):
    """Assign a timeliness tag to an entry."""
    title = entry["title"].lower()
    source_name = entry["source_name"].lower()
    category = entry["category"]

    # 1. Hot searches
    if category == "中文热搜" or any(x in source_name for x in ["微博", "知乎", "b站", "百度", "头条", "抖音", "澎湃", "凤凰", "贴吧"]):
        return "📈 热搜"
    
    # 2. Hot AI news
    if category == "AI与前沿" or any(x in source_name for x in ["openai", "deepmind", "anthropic", "claude", "gemini", "nature", "hugging"]):
        return "🔥 热门"

    # 3. Discussions
    if category == "开发者社区" or any(x in source_name for x in ["hacker news", "reddit", "v2ex", "stack overflow", "lobsters"]):
        return "💬 讨论"

    # 4. Open Source
    if any(x in title for x in ["开源", "open source", "github", "gitee", "release", "v1.", "v2.", "v3."]):
        return "🛠️ 开源"

    # 5. Column Recommendations
    if category == "特色专栏":
        return "💡 推荐"

    return ""


def get_trend_words(entries):
    """Analyze title word frequency to extract trend keywords."""
    word_counts = {}
    for entry in entries:
        title = entry["title"]
        # Remove punctuation
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z\d]+', title)
        for w in words:
            w_lower = w.lower()
            if len(w_lower) < 2:
                continue
            if w_lower in STOP_WORDS:
                continue
            # Exclude numbers
            if w_lower.isdigit():
                continue
            word_counts[w] = word_counts.get(w, 0) + 1
            
    # Sort and return top 15 words
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_words[:15]]


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
    print("NewsFlow - Fetching feeds with analytics & SEO...")
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

    # Assign hot tags first (used for trend analysis and translation priority)
    for entry in all_entries:
        entry["hot_tag"] = assign_hot_tag(entry)

    # Translate top entries (save quota)
    print(f"\nTranslating top {MAX_TRANSLATE_ENTRIES} English titles...")
    for i, entry in enumerate(all_entries[:MAX_TRANSLATE_ENTRIES]):
        if is_english(entry["title"]):
            translated = translate_baidu(entry["title"])
            entry["original_title"] = entry["title"]
            entry["title"] = translated
            time.sleep(1)  # Rate limit: Baidu free tier QPS=1
            print(f"  [{i+1}/{MAX_TRANSLATE_ENTRIES}] {entry.get('original_title', '')[:50]}... → {translated[:50]}...")

    # Set formats
    for entry in all_entries:
        entry["time_ago"] = format_time_ago(entry["published"])
        entry["date_str"] = entry["published"].strftime("%Y-%m-%d %H:%M")

    # Generate Hot Keywords
    trend_words = get_trend_words(all_entries)
    print(f"\nTrend keywords: {', '.join(trend_words)}")

    category_counts = {}
    for entry in all_entries:
        category_counts[entry["category"]] = category_counts.get(entry["category"], 0) + 1

    successful_sources = len({e["source_name"] for e in all_entries})

    # Render Main Page
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    
    cst = timezone(timedelta(hours=8))
    updated_at = datetime.now(cst).strftime("%Y-%m-%d %H:%M CST")

    template = env.get_template("index.html")
    html = template.render(
        entries=all_entries,
        categories=category_names,
        category_counts=category_counts,
        total_sources=total_sources,
        successful_sources=successful_sources,
        total_entries=len(all_entries),
        updated_at=updated_at,
        trend_words=trend_words,
    )

    output_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Render SEO Articles
    print(f"\nGenerating {MAX_SEO_PAGES} SEO article pages...")
    os.makedirs(ARTICLES_DIR, exist_ok=True)
    article_template = env.get_template("article.html")
    
    # We use dynamic absolute url pattern for OG links
    site_url = "https://mask2l.github.io/dailynewsflow/"
    
    for entry in all_entries[:MAX_SEO_PAGES]:
        article_html = article_template.render(
            entry=entry,
            site_url=site_url,
        )
        art_path = os.path.join(ARTICLES_DIR, f"{entry['id']}.html")
        with open(art_path, "w", encoding="utf-8") as f:
            f.write(article_html)

    print(f"\n{'=' * 50}")
    print(f"Done! {len(all_entries)} entries from {successful_sources}/{total_sources} sources")
    print(f"Generated main site and {MAX_SEO_PAGES} SEO articles")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
