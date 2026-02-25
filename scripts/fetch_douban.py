import feedparser
import datetime
import hashlib
import re
from html import unescape
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from pathlib import Path

RSS_SOURCES = [
    ("热映", "https://rsshub.rssforever.com/douban/movie/playing"),
    ("即将上映", "https://rsshub.rssforever.com/douban/movie/coming"),
    ("高分推荐", "https://rsshub.rssforever.com/douban/movie/weekly"),
]

OUTPUT_DIR = Path("content/posts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
POSTER_DIR = Path("static/posters")
POSTER_DIR.mkdir(parents=True, exist_ok=True)

HTTP_TIMEOUT = 8
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


def image_url_ok(url):
    headers = {"User-Agent": USER_AGENT, "Referer": "https://movie.douban.com/"}

    try:
        req = Request(url, headers=headers, method="HEAD")
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            code = getattr(resp, "status", 200)
            if 200 <= code < 400:
                return True
    except Exception:
        pass

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            code = getattr(resp, "status", 200)
            content_type = str(resp.headers.get("Content-Type", "")).lower()
            return 200 <= code < 400 and ("image" in content_type or content_type == "")
    except (HTTPError, URLError, ValueError):
        return False


def replacement_candidates(url):
    candidates = []
    if url.endswith(".webp"):
        candidates.append(url[:-5] + ".jpg")
        candidates.append(url[:-5] + ".jpeg")
        candidates.append(url[:-5] + ".png")

    m = re.match(r"(https://img)(\d)(\.doubanio\.com/.+)", url)
    if m:
        prefix, _, suffix = m.groups()
        for i in range(1, 10):
            host_url = f"{prefix}{i}{suffix}"
            candidates.append(host_url)
            if host_url.endswith(".webp"):
                candidates.append(host_url[:-5] + ".jpg")

    unique = []
    seen = set()
    for item in candidates:
        if item not in seen and item != url:
            seen.add(item)
            unique.append(item)
    return unique


def fetch_text(url):
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.bing.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="ignore")
    except (HTTPError, URLError, ValueError):
        return ""


def candidates_from_source_page(source_link):
    if not source_link:
        return []

    page = fetch_text(source_link)
    if not page:
        return []

    out = []
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<img[^>]+src=["\'](https?://[^"\']+)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, page, flags=re.IGNORECASE):
            url = unescape(match).replace("\\/", "/").strip()
            if url.startswith("http"):
                out.append(url)

    unique = []
    seen = set()
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def candidates_from_web_search(title):
    if not title:
        return []

    query = quote(f"{title} 电影 海报", safe='')
    search_url = f"https://www.bing.com/images/search?q={query}"
    page = fetch_text(search_url)
    if not page:
        return []

    found = []
    for match in re.findall(r'"murl":"(https?:\\/\\/[^"\\]+)"', page):
        found.append(unescape(match).replace("\\/", "/"))
    for match in re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', page, flags=re.IGNORECASE):
        found.append(unescape(match).replace("\\/", "/"))

    unique = []
    seen = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
        if len(unique) >= 15:
            break
    return unique


def guess_image_ext(url, content_type):
    lower_url = url.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if ext in lower_url:
            return ext

    ct = str(content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    return ".jpg"


def fetch_image_bytes(url):
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://movie.douban.com/",
        "Accept": "image/*,*/*;q=0.8",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            code = getattr(resp, "status", 200)
            content_type = str(resp.headers.get("Content-Type", "")).lower()
            if not (200 <= code < 400):
                return b"", ""
            if content_type and "image" not in content_type:
                return b"", ""
            data = resp.read()
            if not data:
                return b"", ""
            return data, content_type
    except (HTTPError, URLError, ValueError):
        return b"", ""


def ensure_local_poster(title, source_link, original_url):
    candidates = []
    if original_url:
        candidates.append(original_url)
        candidates.extend(replacement_candidates(original_url))
    candidates.extend(candidates_from_source_page(source_link))
    candidates.extend(candidates_from_web_search(title))

    seen = set()
    ordered = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)

    for candidate in ordered:
        img_bytes, content_type = fetch_image_bytes(candidate)
        if not img_bytes:
            continue

        key = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:20]
        ext = guess_image_ext(candidate, content_type)
        filename = f"{key}{ext}"
        local_path = POSTER_DIR / filename
        if not local_path.exists():
            local_path.write_bytes(img_bytes)
        return f"/posters/{filename}"

    return ""


def fix_first_image_src(content_html, title="", source_link=""):
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_html, flags=re.IGNORECASE)
    original = m.group(1).strip() if m else ""
    local_src = ensure_local_poster(title, source_link, original)
    if not local_src:
        return content_html

    if m:
        return content_html.replace(original, local_src, 1)

    img = f'<p><img src="{local_src}" referrerpolicy="no-referrer" loading="lazy"></p>'
    return f"{img}\n{content_html}"


def load_existing_indexes():
    existing_titles = set()
    existing_links = set()
    title_re = re.compile(r'^title:\s*"(.*)"\s*$', flags=re.MULTILINE)
    link_re = re.compile(r'\*\[去豆瓣查看原网页\]\(([^)]+)\)\*')

    for path in OUTPUT_DIR.glob("*.md"):
        text = path.read_text(encoding='utf-8')

        title_match = title_re.search(text)
        if title_match:
            existing_titles.add(title_match.group(1).replace('\\"', '"').strip())

        link_match = link_re.search(text)
        if link_match:
            existing_links.add(link_match.group(1).strip())

    return existing_titles, existing_links

def main():
    seen_guids = set()
    existing_titles, existing_links = load_existing_indexes()

    for source_name, url in RSS_SOURCES:
        print(f"⏳ 正在尝试抓取 [{source_name}]: {url}")
        feed = feedparser.parse(url, agent=USER_AGENT)

        if not feed.entries:
            print(f"⚠️ {url} 未抓取到数据。")
            continue

        print(f"✅ [{source_name}] 成功获取到 {len(feed.entries)} 条数据。")

        for entry in feed.entries:
            source_link = str(entry.get('link', '') or '').strip()
            guid = str(entry.get('guid', source_link) or source_link)
            if guid in seen_guids or source_link in existing_links:
                continue
            seen_guids.add(guid)

            title = str(entry.get('title', '') or '').strip()
            if not title or title in existing_titles:
                continue
            safe_title = title.replace('"', '\\"')

            slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]+', '-', title).strip('-').lower()
            date = datetime.datetime.now()
            date_str = date.strftime("%Y-%m-%d")

            search_keyword = quote(title, safe='')
            watch_link = f"https://tv.srfwq.top/?q={search_keyword}"
            description = str(entry.get('description', '') or '')

            front_matter = f"""---
title: "{safe_title}"
date: {date_str}
draft: false
description: "豆瓣{source_name}：{title}"
tags: ["影视推荐", "在线观看", "{source_name}"]
---"""

            cta_button = f"""
<div style="text-align: center; margin: 30px 0;">
  <a href="{watch_link}" target="_blank" style="background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px; display: inline-block; box-shadow: 0 4px 6px rgba(0,123,255,0.2);">
    ▶️ 立即观看高清版：{title}
  </a>
  <p style="font-size: 12px; color: #666; margin-top: 8px;">点击跳转至 SR 极速影院搜索</p>
</div>
"""

            description = fix_first_image_src(description, title=title, source_link=source_link)
            description = re.sub(r"<img(?![^>]*referrerpolicy=)", '<img referrerpolicy="no-referrer" loading="lazy"', description, count=1)
            content = f"{front_matter}\n\n{description}\n\n{cta_button}\n\n*[去豆瓣查看原网页]({entry.link})*"

            filename = f"{date_str}-{slug}.md"
            if (OUTPUT_DIR / filename).exists():
                filename = f"{date_str}-{slug}-{source_name}.md"
            path = OUTPUT_DIR / filename
            path.write_text(content, encoding='utf-8')
            existing_titles.add(title)
            if source_link:
                existing_links.add(source_link)
            print(f"  -> [{source_name}] 新增文章: {filename}")

    print("🎉 抓取任务执行完毕！")


if __name__ == "__main__":
    main()
