#!/usr/bin/env python3
"""Prepare static files for Tencent EdgeOne Pages."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = ROOT / "edgeone-dist"


def copy_file(name: str) -> None:
    shutil.copy2(FRONTEND / name, DIST / name)


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    for name in ("index.html", "styles.css", "app.js", "demo.html", "demo.css", "demo.js"):
        copy_file(name)

    index = DIST / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8")
        .replace('href="/demo.html"', 'href="./demo.html"')
        .replace('href="/styles.css"', 'href="./styles.css"')
        .replace('src="/app.js"', 'src="./app.js"'),
        encoding="utf-8",
    )

    demo = DIST / "demo.html"
    demo.write_text(
        demo.read_text(encoding="utf-8")
        .replace('href="/"', 'href="./"')
        .replace('href="/"', 'href="./"')
        .replace('href="/demo.css"', 'href="./demo.css"')
        .replace('src="/demo.js', 'src="./demo.js'),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
