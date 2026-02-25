import feedparser
import datetime
import hashlib
import json
import re
import time
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

SITE_BASE_URL = "https://wztj.893810.xyz"
BAIDU_PUSH_API = "http://data.zz.baidu.com/urls?site=https://wztj.893810.xyz&token=jFhkTJy8IB7LvvjX"

OUTPUT_DIR = Path("content/posts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
POSTER_DIR = Path("static/posters")
POSTER_DIR.mkdir(parents=True, exist_ok=True)
AUTOMATION_DIR = Path("automation")
AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
PUBLISH_QUEUE_PATH = AUTOMATION_DIR / "publish_queue.json"

HTTP_TIMEOUT = 8
REQUEST_RETRIES = 3
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


def fetch_text(url, referer="https://www.bing.com/"):
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    last_error = ""
    for attempt in range(REQUEST_RETRIES):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read()
                return raw.decode("utf-8", errors="ignore")
        except (HTTPError, URLError, ValueError) as exc:
            last_error = str(exc)
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(1 + attempt)
    print(f"⚠️ fetch_text failed after {REQUEST_RETRIES} retries: {url} ({last_error})")
    return ""


def fetch_json(url, referer="https://movie.douban.com/"):
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    last_error = ""
    for attempt in range(REQUEST_RETRIES):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                return json.loads(raw)
        except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(1 + attempt)
    print(f"⚠️ fetch_json failed after {REQUEST_RETRIES} retries: {url} ({last_error})")
    return {}


def html_to_text(fragment):
    if not fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def dedupe_detail_headings(content):
    def keep_first_heading_block(text, heading):
        pattern = re.compile(
            rf'\s*<h2>\s*{heading}\s*</h2>\s*<p>.*?</p>\s*',
            flags=re.IGNORECASE | re.DOTALL,
        )
        matches = list(pattern.finditer(text))
        if len(matches) <= 1:
            return text
        first = matches[0]
        output = []
        cursor = 0
        for idx, match in enumerate(matches):
            output.append(text[cursor:match.start()])
            if idx == 0:
                output.append(match.group(0))
            cursor = match.end()
        output.append(text[cursor:])
        return "".join(output)

    content = keep_first_heading_block(content, "演员表")
    content = keep_first_heading_block(content, "剧情简介")
    return content


def extract_douban_cast(page_html):
    if not page_html:
        return ""

    patterns = [
        r'<span[^>]*>\s*主演\s*</span>\s*[:：]\s*<span class="attrs">(.*?)</span>',
        r'<span class="pl">\s*主演\s*</span>\s*[:：]\s*(.*?)<br\s*/?>',
    ]

    for pattern in patterns:
        m = re.search(pattern, page_html, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        raw = m.group(1)
        names = [
            html_to_text(name)
            for name in re.findall(r">([^<]+)</a>", raw, flags=re.IGNORECASE | re.DOTALL)
        ]
        names = [name for name in names if name]
        if names:
            return " / ".join(names)
        text = html_to_text(raw)
        if text:
            return text

    return ""


def extract_douban_summary(page_html):
    if not page_html:
        return ""

    patterns = [
        r'<span[^>]*property=["\']v:summary["\'][^>]*>(.*?)</span>',
        r'<span id="link-report-intra"[^>]*>(.*?)</span>\s*</span>',
    ]

    for pattern in patterns:
        m = re.search(pattern, page_html, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        summary = html_to_text(m.group(1))
        if summary:
            return summary

    return ""


def fetch_douban_details(source_link):
    if not source_link:
        return "", ""

    sid_match = re.search(r"/subject/(\d+)", source_link)
    sid = sid_match.group(1) if sid_match else ""

    cast_text = ""
    summary_text = ""

    if sid:
        referer = f"https://m.douban.com/movie/subject/{sid}/"
        detail_api = f"https://m.douban.com/rexxar/api/v2/movie/{sid}?for_mobile=1"
        detail_obj = fetch_json(detail_api, referer=referer)

        cast_names = [
            str(item.get("name", "")).strip()
            for item in detail_obj.get("actors", [])
            if isinstance(item, dict) and item.get("name")
        ]
        cast_text = " / ".join([name for name in cast_names if name])
        summary_text = re.sub(r"\s+", " ", str(detail_obj.get("intro", "") or "")).strip()

        if not (cast_text and summary_text):
            abstract_api = f"https://movie.douban.com/j/subject_abstract?subject_id={sid}"
            abstract_obj = fetch_json(abstract_api, referer="https://movie.douban.com/")
            subject_obj = abstract_obj.get("subject", {}) if isinstance(abstract_obj, dict) else {}
            if not cast_text:
                cast_text = " / ".join([str(x).strip() for x in subject_obj.get("actors", []) if str(x).strip()])
            if not summary_text:
                summary_text = re.sub(r"\s+", " ", str(subject_obj.get("short_intro", "") or "")).strip()

        if cast_text and summary_text:
            return cast_text, summary_text

    page = fetch_text(source_link)
    if not page:
        return cast_text, summary_text

    if not cast_text:
        cast_text = extract_douban_cast(page)
    if not summary_text:
        summary_text = extract_douban_summary(page)
    return cast_text, summary_text


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


def repair_missing_local_poster_ref(content_html, title="", source_link=""):
    m = re.search(r'src=["\'](/posters/[^"\']+)["\']', content_html, flags=re.IGNORECASE)
    if not m:
        return content_html

    current_src = m.group(1)
    current_name = current_src.rsplit('/', 1)[-1]
    if (POSTER_DIR / current_name).exists():
        return content_html

    replacement_src = ensure_local_poster(title, source_link, "")
    if replacement_src:
        print(f"⚠️ poster file missing, replaced: {current_src} -> {replacement_src}")
        return content_html.replace(current_src, replacement_src, 1)

    print(f"⚠️ poster file missing and no replacement found: {current_src}")
    return content_html


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


def load_publish_queue():
    if not PUBLISH_QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(PUBLISH_QUEUE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (ValueError, OSError):
        pass
    return []


def update_publish_queue(new_items):
    if not new_items:
        return

    current = load_publish_queue()
    by_url = {}

    for item in current:
        url = str(item.get("url", "")).strip()
        if url:
            by_url[url] = item

    for item in new_items:
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        by_url[url] = {
            "title": str(item.get("title", "")).strip(),
            "url": url,
            "source": str(item.get("source", "")).strip(),
            "date": str(item.get("date", "")).strip(),
            "file": str(item.get("file", "")).strip(),
            "state": "pending",
            "queued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

    queue = sorted(by_url.values(), key=lambda x: (x.get("date", ""), x.get("url", "")), reverse=True)
    PUBLISH_QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📦 Publish queue updated: {len(queue)} total, +{len(new_items)} new")


def submit_urls_to_baidu(urls):
    if not urls:
        return

    payload = "\n".join(urls).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "text/plain",
    }

    try:
        req = Request(BAIDU_PUSH_API, data=payload, headers=headers, method="POST")
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                print(f"⚠️ Baidu push returned non-JSON: {body[:200]}")
                return

            success = int(result.get("success", 0) or 0)
            remain = result.get("remain")
            not_same_site = int(result.get("not_same_site", 0) or 0)
            not_valid = int(result.get("not_valid", 0) or 0)
            print(
                f"📮 Baidu push: success={success}/{len(urls)} remain={remain} not_same_site={not_same_site} not_valid={not_valid}"
            )
    except Exception as exc:
        print(f"⚠️ Baidu push failed: {exc}")

def main():
    seen_guids = set()
    existing_titles, existing_links = load_existing_indexes()
    total_new_posts = 0
    detail_complete = 0
    detail_partial = 0
    detail_missing = 0
    failed_feeds = 0
    new_post_urls = []
    new_publish_items = []

    for source_name, url in RSS_SOURCES:
        print(f"⏳ 正在尝试抓取 [{source_name}]: {url}")
        feed = feedparser.parse(url, agent=USER_AGENT)

        if not feed.entries:
            print(f"⚠️ {url} 未抓取到数据。")
            failed_feeds += 1
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
            cast_text, summary_text = fetch_douban_details(source_link)
            if cast_text and summary_text:
                detail_complete += 1
            elif cast_text or summary_text:
                detail_partial += 1
                print(f"⚠️ [{title}] details partial: cast={bool(cast_text)} summary={bool(summary_text)}")
            else:
                detail_missing += 1
                print(f"⚠️ [{title}] details missing entirely: {source_link}")

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
            description = repair_missing_local_poster_ref(description, title=title, source_link=source_link)
            description = re.sub(r"<img(?![^>]*referrerpolicy=)", '<img referrerpolicy="no-referrer" loading="lazy"', description, count=1)

            detail_blocks = []
            has_cast_in_description = bool(re.search(r"(主演|演员)\s*[:：]", description))
            has_summary_in_description = bool(re.search(r"<h2[^>]*>\s*剧情简介\s*</h2>", description, flags=re.IGNORECASE))

            if cast_text and not has_cast_in_description:
                detail_blocks.append(f"<h2>演员表</h2><p>{cast_text}</p>")
            if summary_text and not has_summary_in_description:
                detail_blocks.append(f"<h2>剧情简介</h2><p>{summary_text.replace(chr(10), '<br>')}</p>")
            details_html = "\n\n".join(detail_blocks)

            if details_html:
                content = f"{front_matter}\n\n{description}\n\n{details_html}\n\n{cta_button}\n\n*[去豆瓣查看原网页]({entry.link})*"
            else:
                content = f"{front_matter}\n\n{description}\n\n{cta_button}\n\n*[去豆瓣查看原网页]({entry.link})*"
            content = dedupe_detail_headings(content)

            filename = f"{date_str}-{slug}.md"
            if (OUTPUT_DIR / filename).exists():
                filename = f"{date_str}-{slug}-{source_name}.md"
            path = OUTPUT_DIR / filename
            path.write_text(content, encoding='utf-8')
            total_new_posts += 1
            post_stem = Path(filename).stem
            post_url = f"{SITE_BASE_URL}/posts/{quote(post_stem, safe='-._~')}/"
            new_post_urls.append(post_url)
            new_publish_items.append({
                "title": title,
                "url": post_url,
                "source": source_name,
                "date": date_str,
                "file": filename,
            })
            existing_titles.add(title)
            if source_link:
                existing_links.add(source_link)
            print(f"  -> [{source_name}] 新增文章: {filename}")

    print("🎉 抓取任务执行完毕！")
    print(
        f"📊 统计：新增={total_new_posts} 完整详情={detail_complete} 部分详情={detail_partial} 缺失详情={detail_missing} 失败源={failed_feeds}/{len(RSS_SOURCES)}"
    )

    if new_post_urls:
        dedup_urls = list(dict.fromkeys(new_post_urls))
        submit_urls_to_baidu(dedup_urls)
        update_publish_queue(new_publish_items)

    if failed_feeds == len(RSS_SOURCES):
        raise RuntimeError("All RSS sources failed")


if __name__ == "__main__":
    main()
