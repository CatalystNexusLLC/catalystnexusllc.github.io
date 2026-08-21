from __future__ import annotations

import argparse
import shutil
from pathlib import Path

DEFAULT_PRODUCTION_API_BASE_URL = "https://api.beta.example.com"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="_site")
    parser.add_argument("--api-base-url", default="")
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "site"
    target = Path(args.output).resolve()
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    api_base_url = args.api_base_url.strip()
    if args.production and not api_base_url:
        api_base_url = DEFAULT_PRODUCTION_API_BASE_URL
    if api_base_url:
        config = target / "portal-config.js"
        text = config.read_text(encoding="utf-8")
        text = text.replace('apiBaseUrl: "https://api.example.invalid"', f'apiBaseUrl: "{api_base_url.rstrip("/")}"')
        config.write_text(text, encoding="utf-8")
    if args.production and "example.invalid" in (target / "portal-config.js").read_text(encoding="utf-8"):
        raise SystemExit("production build requires --api-base-url")
    (target / ".nojekyll").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
