import json
import datetime
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


AUTOMATION_DIR = Path("automation")
AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_PATH = AUTOMATION_DIR / "publish_queue.json"
STATUS_PATH = AUTOMATION_DIR / "publish_status.json"
TARGET_PLATFORMS = ["baijiahao", "toutiao"]
HTTP_TIMEOUT = 12
MAX_ATTEMPTS = 3


PLATFORM_CONFIG = {
    "baijiahao": {
        "endpoint_env": "BAIJIAHAO_PUBLISH_ENDPOINT",
        "token_env": "BAIJIAHAO_PUBLISH_TOKEN",
    },
    "toutiao": {
        "endpoint_env": "TOUTIAO_PUBLISH_ENDPOINT",
        "token_env": "TOUTIAO_PUBLISH_TOKEN",
    },
}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (ValueError, OSError):
        return default


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_payload(base_item):
    return {
        "title": str(base_item.get("title", "")).strip(),
        "url": str(base_item.get("url", "")).strip(),
        "source": str(base_item.get("source", "")).strip(),
        "date": str(base_item.get("date", "")).strip(),
        "file": str(base_item.get("file", "")).strip(),
    }


def post_to_platform(platform, payload):
    cfg = PLATFORM_CONFIG.get(platform, {})
    endpoint = os.getenv(cfg.get("endpoint_env", ""), "").strip()
    token = os.getenv(cfg.get("token_env", ""), "").strip()

    if not endpoint:
        base = os.getenv("PUBLISH_GATEWAY_BASE_URL", "").strip().rstrip("/")
        if base:
            endpoint = f"{base}/publish/{platform}"

    if not endpoint:
        return {
            "status": "queued",
            "message": f"missing endpoint env: {cfg.get('endpoint_env', 'N/A')} and no PUBLISH_GATEWAY_BASE_URL",
            "http_code": None,
        }

    req_payload = dict(payload)
    req_payload["platform"] = platform
    body = json.dumps(req_payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "SRFWQSPublisher/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = Request(endpoint, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            code = int(getattr(resp, "status", 200))
            ok = 200 <= code < 300
            msg = raw[:400] if raw else "ok"
            return {
                "status": "success" if ok else "failed",
                "message": msg,
                "http_code": code,
            }
    except HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = str(exc)
        return {
            "status": "failed",
            "message": f"HTTPError {exc.code}: {err_body[:300]}",
            "http_code": int(exc.code),
        }
    except (URLError, ValueError, TimeoutError) as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "http_code": None,
        }


def main():
    queue = load_json(QUEUE_PATH, [])
    status = load_json(STATUS_PATH, {"items": {}, "updated_at": ""})
    items = status.get("items", {}) if isinstance(status, dict) else {}
    prev_updated_at = status.get("updated_at", "") if isinstance(status, dict) else ""

    touched = 0
    now = now_iso()

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

        payload = build_payload({
            "title": items[url].get("title", ""),
            "url": url,
            "source": items[url].get("source", ""),
            "date": items[url].get("date", ""),
            "file": items[url].get("file", ""),
        })

        for platform in TARGET_PLATFORMS:
            if platform not in items[url]["platforms"]:
                items[url]["platforms"][platform] = {
                    "status": "queued",
                    "last_attempt_at": "",
                    "attempts": 0,
                    "message": "MVP queue only, publisher adapter pending",
                }
                touched += 1

            slot = items[url]["platforms"][platform]
            status = str(slot.get("status", "queued"))
            attempts = int(slot.get("attempts", 0) or 0)

            if status == "success":
                continue
            if attempts >= MAX_ATTEMPTS:
                continue

            result = post_to_platform(platform, payload)
            slot["status"] = result["status"]
            slot["last_attempt_at"] = now_iso()
            slot["attempts"] = attempts + 1
            slot["message"] = result["message"]
            slot["http_code"] = result["http_code"]
            touched += 1

    if touched == 0:
        print(f"📣 Publish dispatcher: queue={len(queue)} tracked={len(items)} no state changes")
        return

    output = {
        "items": items,
        "updated_at": now_iso() if touched > 0 else prev_updated_at,
    }
    STATUS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"📣 Publish dispatcher: queue={len(queue)} tracked={len(items)} changed={touched}")


if __name__ == "__main__":
    main()
