import argparse
import json
import re
import webbrowser
from pathlib import Path


AUTOMATION_DIR = Path("automation")
QUEUE_PATH = AUTOMATION_DIR / "publish_queue.json"
STATUS_PATH = AUTOMATION_DIR / "publish_status.json"
POSTS_DIR = Path("content/posts")
ASSIST_DIR = AUTOMATION_DIR / "publish_assist"
ASSIST_HTML = ASSIST_DIR / "index.html"

PLATFORM_PUBLISH_URLS = {
    "baijiahao": "https://baijiahao.baidu.com/builder/rc/edit",
    "toutiao": "https://mp.toutiao.com/profile_v4/graphic/publish",
}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def strip_front_matter(text):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def html_to_plain(text):
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_body(item):
    post_file = POSTS_DIR / str(item.get("file", "")).strip()
    if not post_file.exists():
        return f"{item.get('title', '')}\n\n原文链接：{item.get('url', '')}"

    raw = post_file.read_text(encoding="utf-8")
    body = html_to_plain(strip_front_matter(raw))
    body = re.sub(r"\*\[去豆瓣查看原网页\]\([^)]*\)\*", "", body)
    body = body.strip()

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    excerpt = "\n".join(lines[:24])
    return f"{excerpt}\n\n原文链接：{item.get('url', '')}"


def pending_tasks(queue, status):
    result = []
    items = status.get("items", {}) if isinstance(status, dict) else {}

    for item in queue:
        url = str(item.get("url", "")).strip()
        if not url:
            continue

        platform_state = items.get(url, {}).get("platforms", {})
        body = build_body(item)

        for platform in ("baijiahao", "toutiao"):
            p = platform_state.get(platform, {})
            if str(p.get("status", "queued")) == "success":
                continue

            result.append(
                {
                    "platform": platform,
                    "title": str(item.get("title", "")).strip(),
                    "url": url,
                    "publish_url": PLATFORM_PUBLISH_URLS[platform],
                    "body": body,
                }
            )

    return result


def render_html(tasks):
    data = json.dumps(tasks, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>发布助手</title>
  <style>
    body {{ font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif; margin: 18px; background: #f4f6f8; color: #1f2937; }}
    .card {{ background: #fff; border: 1px solid #d1d5db; border-radius: 10px; padding: 14px; margin-bottom: 12px; }}
    .meta {{ font-size: 12px; color: #6b7280; margin-bottom: 8px; }}
    .actions button {{ margin-right: 8px; margin-top: 8px; border: 0; border-radius: 8px; padding: 8px 10px; cursor: pointer; }}
    .open {{ background: #0f766e; color: #fff; }}
    .copy {{ background: #1d4ed8; color: #fff; }}
    .hint {{ font-size: 12px; color: #6b7280; }}
  </style>
</head>
<body>
  <h2>平台发布助手（半自动）</h2>
  <p class=\"hint\">步骤：先点\"打开发布页\"，再点\"复制标题/正文\"粘贴到后台发布。</p>
  <div id=\"list\"></div>
  <script>
    const tasks = {data};
    const list = document.getElementById('list');

    function btn(text, cls, onClick) {{
      const b = document.createElement('button');
      b.textContent = text;
      b.className = cls;
      b.onclick = onClick;
      return b;
    }}

    async function copyText(text) {{
      try {{
        await navigator.clipboard.writeText(text);
        alert('已复制到剪贴板');
      }} catch (e) {{
        alert('复制失败，请手动复制');
      }}
    }}

    if (!tasks.length) {{
      const e = document.createElement('p');
      e.textContent = '当前没有待发布任务。';
      list.appendChild(e);
    }}

    tasks.forEach((t, i) => {{
      const c = document.createElement('div');
      c.className = 'card';

      const title = document.createElement('div');
      title.innerHTML = `<strong>[${{t.platform}}] ${{t.title}}</strong>`;
      c.appendChild(title);

      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = t.url;
      c.appendChild(meta);

      const actions = document.createElement('div');
      actions.className = 'actions';
      actions.appendChild(btn('打开发布页', 'open', () => window.open(t.publish_url, '_blank')));
      actions.appendChild(btn('复制标题', 'copy', () => copyText(t.title)));
      actions.appendChild(btn('复制正文', 'copy', () => copyText(t.body)));
      actions.appendChild(btn('复制原文链接', 'copy', () => copyText(t.url)));
      c.appendChild(actions);

      list.appendChild(c);
    }});
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Open semi-automatic publish helper page")
    parser.add_argument("--open", action="store_true", help="Open helper page in browser")
    args = parser.parse_args()

    queue = load_json(QUEUE_PATH, [])
    status = load_json(STATUS_PATH, {"items": {}, "updated_at": ""})
    tasks = pending_tasks(queue, status)

    ASSIST_DIR.mkdir(parents=True, exist_ok=True)
    ASSIST_HTML.write_text(render_html(tasks), encoding="utf-8")
    print(f"🧰 Publish helper generated: {ASSIST_HTML} (tasks={len(tasks)})")

    if args.open:
        webbrowser.open(ASSIST_HTML.resolve().as_uri())


if __name__ == "__main__":
    main()
