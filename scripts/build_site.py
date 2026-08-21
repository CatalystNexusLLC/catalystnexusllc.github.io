from __future__ import annotations

import argparse
import shutil
from pathlib import Path


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
    if args.api_base_url:
        config = target / "portal-config.js"
        text = config.read_text(encoding="utf-8")
        text = text.replace('apiBaseUrl: "https://api.example.invalid"', f'apiBaseUrl: "{args.api_base_url.rstrip("/")}"')
        config.write_text(text, encoding="utf-8")
    if args.production and "example.invalid" in (target / "portal-config.js").read_text(encoding="utf-8"):
        raise SystemExit("production build requires --api-base-url")
    (target / ".nojekyll").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
