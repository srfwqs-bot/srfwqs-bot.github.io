import json
import datetime
from pathlib import Path


AUTOMATION_DIR = Path("automation")
AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_PATH = AUTOMATION_DIR / "publish_queue.json"
STATUS_PATH = AUTOMATION_DIR / "publish_status.json"
TARGET_PLATFORMS = ["baijiahao", "toutiao"]


def load_json(path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (ValueError, OSError):
        return default


def main():
    queue = load_json(QUEUE_PATH, [])
    status = load_json(STATUS_PATH, {"items": {}, "updated_at": ""})
    items = status.get("items", {}) if isinstance(status, dict) else {}

    touched = 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    for item in queue:
        url = str(item.get("url", "")).strip()
        if not url:
            continue

        if url not in items:
            items[url] = {
                "title": str(item.get("title", "")).strip(),
                "source": str(item.get("source", "")).strip(),
                "date": str(item.get("date", "")).strip(),
                "file": str(item.get("file", "")).strip(),
                "platforms": {},
                "created_at": now,
            }

        for platform in TARGET_PLATFORMS:
            if platform not in items[url]["platforms"]:
                items[url]["platforms"][platform] = {
                    "status": "queued",
                    "last_attempt_at": "",
                    "message": "MVP queue only, publisher adapter pending",
                }
                touched += 1

    output = {
        "items": items,
        "updated_at": now,
    }
    STATUS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"📣 Publish dispatcher: queue={len(queue)} tracked={len(items)} new_platform_slots={touched}")


if __name__ == "__main__":
    main()
