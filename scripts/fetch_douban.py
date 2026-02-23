import feedparser
import os
import datetime
import re
from pathlib import Path

# 更换了更稳定的 RSSHub 公共镜像源 (rsshub.rssforever.com)
RSS_URLS = [
    "https://rsshub.rssforever.com/douban/movie/playing/7.5",
    "https://rsshub.rssforever.com/douban/movie/weekly",
    "https://rsshub.rssforever.com/douban/movie/coming"
]

OUTPUT_DIR = Path("content/posts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

seen_guids = set()

for url in RSS_URLS:
    print(f"⏳ 正在尝试抓取: {url}")
    # 添加 headers 伪装成正常浏览器，降低被拦截的概率
    feed = feedparser.parse(url, agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # 检查是否抓到数据
    if not feed.entries:
        print(f"⚠️ {url} 未抓取到数据，可能被限流或节点网络不通。")
        if hasattr(feed, 'status'):
            print(f"   HTTP 状态码: {feed.status}")
        continue

    print(f"✅ 成功连接源！获取到 {len(feed.entries)} 条数据。")

    for entry in feed.entries:
        guid = entry.get('guid', entry.link)
        if guid in seen_guids:
            continue
        seen_guids.add(guid)
        
        title = entry.title
        slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]+', '-', title).strip('-').lower()
        date = datetime.datetime(*entry.published_parsed[:6]) if 'published_parsed' in entry else datetime.datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        
        search_keyword = title.replace(' ', '%20')
        watch_link = f"https://tv.srfwq.top/search/{search_keyword}"
        
        description = entry.get('description', '')
        
        front_matter = f"""---
title: "{title.replace('"', '\\"')}"
date: {date_str}
draft: false
description: "豆瓣高分推荐：{title}"
tags: ["影视推荐", "在线观看"]
---"""
        
        cta_button = f"""
<div style="text-align: center; margin: 30px 0;">
  <a href="{watch_link}" target="_blank" style="background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px; display: inline-block; box-shadow: 0 4px 6px rgba(0,123,255,0.2);">
    ▶️ 立即观看高清版：{title}
  </a>
  <p style="font-size: 12px; color: #666; margin-top: 8px;">点击跳转至 SR 极速影院搜索</p>
</div>
"""
        
        content = f"{front_matter}\n\n{description}\n\n{cta_button}\n\n*[去豆瓣查看原网页]({entry.link})*"
        
        filename = f"{date_str}-{slug}.md"
        path = OUTPUT_DIR / filename
        path.write_text(content, encoding='utf-8')
        print(f"  -> 新增文章: {filename}")

print("🎉 抓取任务执行完毕！")