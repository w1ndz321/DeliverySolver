#!/usr/bin/env python3
"""Build static fallback payloads for the GitHub Pages demo."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from tempfile import gettempdir


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "demo-fallback.js"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def scrub(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in {"input_text", "solution"}:
                continue
            if key in {"state_root", "memory_path", "path", "latest_path", "final_submit_path", "module_path", "code_path"}:
                cleaned[key] = public_path(item)
            else:
                cleaned[key] = scrub(item)
        return cleaned
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return public_path(value)
    return value


def public_path(value):
    text = str(value)
    markers = ["/submission/", "\\submission\\"]
    for marker in markers:
        if marker in text:
            return text.split(marker, 1)[1].replace("\\", "/")
    tmp = str(gettempdir())
    if text.startswith(tmp):
        name = Path(text).name
        return f"demo_sandbox/{name}" if name else "demo_sandbox"
    return text.replace(str(ROOT), "").lstrip("/").replace("\\", "/")


def main() -> None:
    from backend.app import build_offline_demo, build_online_demo, large_seed_snapshot

    online = build_online_demo(10, 301, {}, None, "large_seed301", "static_fallback")
    offline = build_offline_demo(10, 301, {}, {"max_iterations": 5}, None, None, "large_seed301", "static_fallback")
    payload = {
        "snapshot": scrub(large_seed_snapshot()),
        "online": scrub(online),
        "offline": scrub(offline),
        "built_from": "recorded_large_seed301_closed_loop",
    }
    OUT.write_text(
        "window.AUTOSOLVER_STATIC_FALLBACK = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    # The demo builders create temporary sandbox state. Remove it after extracting
    # the public payload so local builds do not accumulate files.
    for result in (online, offline):
        state_root = result.get("demo_state", {}).get("state_root")
        if state_root and str(state_root).startswith(str(gettempdir())):
            shutil.rmtree(state_root, ignore_errors=True)


if __name__ == "__main__":
    main()
