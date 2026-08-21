from __future__ import annotations

import re
from pathlib import Path

PIN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if "uses:" not in stripped:
            continue
        value = stripped.split("uses:", 1)[1].strip().strip('"\'')
        if value.startswith("./") or value.startswith("docker://"):
            continue
        if "@" not in value or not PIN.fullmatch(value.rsplit("@", 1)[1]):
            errors.append(f"{path.relative_to(ROOT)}:{number}: action is not pinned by full commit SHA: {value}")
if errors:
    raise SystemExit("\n".join(errors))
print("All external workflow actions are pinned by full commit SHA.")
