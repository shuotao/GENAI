#!/usr/bin/env python3
"""
dict/load.py — 共用詞典載入器

用法:
    from dict.load import load_typo_dict, load_hallucination_prefixes
    typo = load_typo_dict(domain="parenting")   # base + overlay
    prefixes = load_hallucination_prefixes()

CLI:
    python3 dict/load.py                        # 列出 base typo_dict
    python3 dict/load.py --domain parenting     # base + parenting overlay
    python3 dict/load.py --list-domains         # 列出可用 domain
    python3 dict/load.py --prefixes             # 列出幻覺前綴
"""

import json
import sys
import argparse
from pathlib import Path

DICT_DIR = Path(__file__).resolve().parent


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_typo_dict(domain: str | None = None) -> dict[str, str]:
    """Load base typo_dict.json + optional domain overlay.

    Returns a flat dict {wrong: correct}. Domain entries override base on conflict.
    """
    base = _read_json(DICT_DIR / "typo_dict.json")["corrections"]
    if not domain:
        return dict(base)

    overlay_path = DICT_DIR / f"typo_dict.{domain}.json"
    if not overlay_path.exists():
        print(
            f"[dict] warning: typo_dict.{domain}.json not found, using base only",
            file=sys.stderr,
        )
        return dict(base)

    overlay = _read_json(overlay_path)["corrections"]
    merged = dict(base)
    merged.update(overlay)
    return merged


def load_hallucination_prefixes() -> list[str]:
    return _read_json(DICT_DIR / "hallucination_prefixes.json")["prefixes"]


def list_domains() -> list[str]:
    """Discover available domain overlays by scanning dict/ directory."""
    domains = []
    for p in DICT_DIR.glob("typo_dict.*.json"):
        # typo_dict.parenting.json -> parenting
        name = p.stem  # 'typo_dict.parenting'
        parts = name.split(".", 1)
        if len(parts) == 2:
            domains.append(parts[1])
    return sorted(domains)


def main():
    parser = argparse.ArgumentParser(description="Inspect shared dictionaries")
    parser.add_argument("--domain", help="Domain overlay to merge, e.g. parenting")
    parser.add_argument("--list-domains", action="store_true", help="List available domains")
    parser.add_argument("--prefixes", action="store_true", help="Show hallucination prefixes")
    args = parser.parse_args()

    if args.list_domains:
        for d in list_domains():
            print(d)
        return

    if args.prefixes:
        for p in load_hallucination_prefixes():
            print(p)
        return

    merged = load_typo_dict(domain=args.domain)
    # Pretty output: tab-separated wrong\tcorrect
    for wrong, correct in merged.items():
        print(f"{wrong}\t{correct}")
    print(f"\n# total: {len(merged)} entries"
          f"{' (base only)' if not args.domain else f' (base + {args.domain})'}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
