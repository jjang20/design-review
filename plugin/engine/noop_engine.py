#!/usr/bin/env python3
"""Empty review engine (S0-1).

Reads one queue request as JSON on stdin and writes one result as JSON on
stdout. It judges nothing: it only proves that the worker can hand a request
to a fixed script and carry the answer back to the dashboard (SPEC §2.2,
§6.3-1). The real engine replaces this file in S2.

    echo '{"id":"r1","type":"ping","payload":{"echo":"hi"}}' | python3 noop_engine.py
"""
import json
import sys
from datetime import datetime, timezone

ENGINE_VERSION = "0.0.0-noop"
KNOWN_TYPES = {"ping", "import", "review", "propose"}
MAX_ECHO_CHARS = 2000


def run(request, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    req_type = request.get("type")
    if req_type not in KNOWN_TYPES:
        return {"ok": False, "error": f"unknown request type: {req_type!r}",
                "engine_version": ENGINE_VERSION, "processed_at": stamp}
    payload = request.get("payload") or {}
    echo = str(payload.get("echo", ""))[:MAX_ECHO_CHARS]
    return {
        "ok": True,
        "engine_version": ENGINE_VERSION,
        "processed_at": stamp,
        "summary": f"빈 엔진이 '{req_type}' 요청을 받았습니다. 판정은 하지 않습니다.",
        "echo": echo,
    }


def main():
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        json.dump({"ok": False, "error": f"bad request JSON: {e}", "engine_version": ENGINE_VERSION}, sys.stdout)
        return 1
    result = run(request)
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
