from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
TERMS = SITE / "BETA_TESTING_TERMS_v0.2.1.txt"
EXPECTED_TERMS = "2bbbea4db70594425ddf95560c85b4c2ad8bbb35b533eee87ec07e8f67d2b317"
required = ["index.html", "styles.css", "app.js", "portal-config.js", "terms.html", "privacy.html", "releases.json", TERMS.name]
missing = [name for name in required if not (SITE / name).is_file()]
if missing:
    raise SystemExit("missing portal files: " + ", ".join(missing))
actual = hashlib.sha256(TERMS.read_bytes()).hexdigest()
if actual != EXPECTED_TERMS:
    raise SystemExit(f"terms digest mismatch: {actual}")
config = (SITE / "portal-config.js").read_text(encoding="utf-8")
for value in ("0.2.1", "v0.2.1", EXPECTED_TERMS, "CatalystNexusLLC/aurion_beta_launcher"):
    if value not in config:
        raise SystemExit(f"portal config is missing {value}")
catalog = json.loads((SITE / "releases.json").read_text(encoding="utf-8"))
if catalog.get("schema") != "catalyst-nexus-aurion-beta-release/0.2.1":
    raise SystemExit("release catalog schema mismatch")
release = catalog.get("release_set") or {}
if release.get("release_repository") != "CatalystNexusLLC/aurion_beta_launcher" or release.get("release_tag") != "v0.2.1":
    raise SystemExit("release catalog is not pinned to the launcher repository and tag")
if release.get("public_distribution_authorized") is not True:
    if any(asset.get("enabled") is not False for asset in catalog.get("assets", [])):
        raise SystemExit("pending catalog contains an enabled asset")
for html in ("index.html", "terms.html", "privacy.html"):
    text = (SITE / html).read_text(encoding="utf-8")
    if not re.search(r"<html[^>]+lang=", text, re.IGNORECASE):
        raise SystemExit(f"{html} does not declare a language")
print("Portal validation passed.")
