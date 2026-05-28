"""CLI and persistence entry point for case profiling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .feature_extractor import extract_case_profile


def analyze_case(input_text: str, output_path: str | Path | None = None) -> dict:
    profile = extract_case_profile(input_text)
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate case_profile.json for a TSV case.")
    parser.add_argument("case")
    parser.add_argument("--output", default="outputs/case_profile.json")
    args = parser.parse_args()
    profile = analyze_case(Path(args.case).read_text(), args.output)
    print(json.dumps(profile, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
