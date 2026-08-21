from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

COMPONENTS = [
    {"service_role":"synapse.brain","repository":"CatalystNexusLLC/synapse_mcp","version":"2.0.0-alpha","tag":"v2.0.0-alpha","commit_sha":"a5e6a99dc78e5c67ea28682bbaff7fddd8c77146"},
    {"service_role":"aurion.interface","repository":"CatalystNexusLLC/aurion_avatar","version":"1.1.0-alpha","tag":"v1.1.0-alpha","commit_sha":"2c8c7d92e767e4ba564a326ac8f1c3e1ad8673e4"},
    {"service_role":"aurion.workers","repository":"CatalystNexusLLC/aurion_arbiter","version":"0.1.0-alpha","tag":"v0.1.0-alpha","commit_sha":"ea950b079e14f4323902bde5ec5c3a3f8cbbcf4a"},
]
TERMS_VERSION = "AURION-BETA-TERMS-0.2.1"
TERMS_SHA = "2bbbea4db70594425ddf95560c85b4c2ad8bbb35b533eee87ec07e8f67d2b317"
AUTHORIZATION = "AUTHORIZE AURION BETA 0.2.1 PUBLIC RELEASE"
AUTHORITY_SCHEMA = "catalyst-nexus-aurion-release-authority/0.2.1"
PLACEHOLDER = re.compile(r"(?:PENDING|REQUIRED|REPLACE|TBD|TODO|EXAMPLE)", re.IGNORECASE)
HEX40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
HEX64 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def gh_json(endpoint: str) -> dict:
    result = subprocess.run(
        ["gh", "api", endpoint, "-H", "X-GitHub-Api-Version: 2026-03-10"],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip() or f"GitHub API request failed: {endpoint}")
    return json.loads(result.stdout)


def gh_download(repository: str, tag: str, names: list[str], directory: Path) -> None:
    for name in names:
        result = subprocess.run(
            ["gh", "release", "download", tag, "--repo", repository, "--pattern", name, "--dir", str(directory)],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise SystemExit(result.stderr.strip() or f"failed to download release asset {name}")


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: dict) -> str:
    copy = {key: item for key, item in value.items() if key != "catalog_sha256"}
    return hashlib.sha256(json.dumps(copy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or PLACEHOLDER.search(text):
        raise SystemExit(f"{label} is missing or contains a placeholder")
    return text


def require_timestamp(value: object, label: str) -> str:
    text = require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SystemExit(f"{label} must include a timezone")
    return text


def parse_checksums(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, name = line.split("  ", 1)
        except ValueError as exc:
            raise SystemExit(f"malformed SHA256SUMS.txt line {number}") from exc
        if not HEX64.fullmatch(digest) or Path(name).name != name or name in values:
            raise SystemExit(f"invalid or duplicate checksum line {number}")
        values[name] = digest.lower()
    return values


def resolve_annotated_tag(repository: str, tag: str) -> str:
    tag_ref = gh_json(f"repos/{repository}/git/ref/tags/{quote(tag, safe='')}")
    obj = tag_ref.get("object") or {}
    if obj.get("type") != "tag":
        raise SystemExit("the launcher release tag must be an annotated tag")
    tag_object = gh_json(f"repos/{repository}/git/tags/{obj.get('sha')}")
    target = tag_object.get("object") or {}
    if target.get("type") != "commit" or not HEX40.fullmatch(str(target.get("sha") or "")):
        raise SystemExit("annotated tag does not resolve directly to a full commit")
    return str(target["sha"]).lower()


def validate_authority(authority: dict, *, repository: str, tag: str, launcher_commit: str, manifest_sha: str, license_sha: str) -> None:
    if authority.get("schema") != AUTHORITY_SCHEMA or authority.get("authorization") != AUTHORIZATION:
        raise SystemExit("release authority schema or exact authorization phrase is invalid")
    if authority.get("release_repository") != repository or authority.get("release_tag") != tag:
        raise SystemExit("release authority repository or tag mismatch")
    if str(authority.get("launcher_commit_sha") or "").lower() != launcher_commit:
        raise SystemExit("release authority launcher commit does not match the annotated tag")
    if str(authority.get("manifest_sha256") or "").lower() != manifest_sha:
        raise SystemExit("release authority manifest digest mismatch")
    terms = authority.get("terms") or {}
    if terms.get("version") != TERMS_VERSION or terms.get("sha256") != TERMS_SHA:
        raise SystemExit("release authority terms identity mismatch")
    expected_components = {item["repository"]: item["commit_sha"] for item in COMPONENTS}
    if authority.get("components") != expected_components:
        raise SystemExit("release authority component commits do not match the fixed release set")
    license_record = authority.get("license") or {}
    require_text(license_record.get("id"), "license.id")
    if license_record.get("path") != "LICENSE.txt" or str(license_record.get("sha256") or "").lower() != license_sha:
        raise SystemExit("release authority license path or digest mismatch")
    permissions = authority.get("permissions") or {}
    for key in ("public_source", "external_beta_registration", "direct_installer_download"):
        if permissions.get(key) is not True:
            raise SystemExit(f"release authority must explicitly enable {key}")
    if not isinstance(permissions.get("sponsor_registration"), bool):
        raise SystemExit("release authority sponsor_registration must be a boolean")
    approval = authority.get("owner_approval") or {}
    if approval.get("approved_by") != "Guy Grubbs":
        raise SystemExit("release authority must identify Guy Grubbs as the approving owner")
    require_timestamp(approval.get("approved_at"), "owner_approval.approved_at")
    require_text(approval.get("approval_reference"), "owner_approval.approval_reference")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--authorize-public", action="store_true")
    parser.add_argument("--authority", help="Release authority JSON required with --authorize-public")
    args = parser.parse_args()

    if args.repository != "CatalystNexusLLC/aurion_beta_launcher" or args.tag != "v0.2.1":
        raise SystemExit("catalog synchronization is pinned to CatalystNexusLLC/aurion_beta_launcher v0.2.1")

    repository_api = gh_json(f"repos/{args.repository}")
    release_api = gh_json(f"repos/{args.repository}/releases/tags/{args.tag}")
    launcher_commit = resolve_annotated_tag(args.repository, args.tag)
    if release_api.get("draft") is True:
        raise SystemExit("draft releases cannot be published through the portal")

    api_assets = {str(item.get("name")): item for item in release_api.get("assets", [])}
    required_names = [
        "CatalystNexus_AURION_Beta_Launcher_v0.2.1.zip",
        "AURION-Beta-Launcher-v0.2.1.pyz",
        "CatalystNexus_AURION_Beta_Launcher_PDFs_v0.2.1.zip",
        "RELEASE_MANIFEST_v0.2.1.json",
        "SHA256SUMS.txt",
    ]
    missing = [name for name in required_names if name not in api_assets]
    if missing:
        raise SystemExit("GitHub release is missing required assets: " + ", ".join(missing))

    with tempfile.TemporaryDirectory(prefix="aurion-catalog-") as temp:
        temp_dir = Path(temp)
        gh_download(args.repository, args.tag, ["SHA256SUMS.txt", "RELEASE_MANIFEST_v0.2.1.json"], temp_dir)
        checksums_path = temp_dir / "SHA256SUMS.txt"
        manifest_path = temp_dir / "RELEASE_MANIFEST_v0.2.1.json"
        checksums = parse_checksums(checksums_path)
        manifest_sha = file_sha(manifest_path)
        if checksums.get(manifest_path.name) != manifest_sha:
            raise SystemExit("release manifest is not bound by SHA256SUMS.txt")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "catalyst-nexus-aurion-launcher-release-manifest/0.2.1":
            raise SystemExit("unexpected release manifest schema")
        if manifest.get("version") != "0.2.1" or manifest.get("tag") != args.tag:
            raise SystemExit("release manifest version or tag mismatch")
        if str(manifest.get("launcher_commit_sha") or "").lower() != launcher_commit:
            raise SystemExit("release manifest launcher commit does not match the annotated tag")
        if (manifest.get("terms") or {}) != {"version": TERMS_VERSION, "sha256": TERMS_SHA}:
            raise SystemExit("release manifest terms identity mismatch")
        observed_components = {
            str(item.get("repository")): str(item.get("upstream_commit"))
            for item in manifest.get("component_payloads", [])
        }
        expected_components = {item["repository"]: item["commit_sha"] for item in COMPONENTS}
        if observed_components != expected_components:
            raise SystemExit("release manifest component source identities do not match the fixed release set")

        license_api = gh_json(f"repos/{args.repository}/contents/LICENSE.txt?ref={quote(args.tag, safe='')}")
        license_bytes = base64.b64decode(str(license_api.get("content") or "").replace("\n", ""), validate=True)
        license_sha = hashlib.sha256(license_bytes).hexdigest()

        authority: dict = {}
        if args.authorize_public:
            if repository_api.get("private") is True:
                raise SystemExit("public source authorization requires the launcher repository to be public")
            if not args.authority:
                raise SystemExit("--authority is required for public authorization")
            authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
            validate_authority(
                authority,
                repository=args.repository,
                tag=args.tag,
                launcher_commit=launcher_commit,
                manifest_sha=manifest_sha,
                license_sha=license_sha,
            )

        definitions = {
            "CatalystNexus_AURION_Beta_Launcher_v0.2.1.zip": ("complete", "Complete release ZIP", "windows-macos-linux", "complete-release"),
            "AURION-Beta-Launcher-v0.2.1.pyz": ("universal", "Universal Python launcher", "python-3.11-3.14", "python-zipapp"),
            "CatalystNexus_AURION_Beta_Launcher_PDFs_v0.2.1.zip": ("pdfs", "Release documentation PDFs", "documentation", "pdf-bundle"),
            "RELEASE_MANIFEST_v0.2.1.json": ("manifest", "Machine-readable release manifest", "verification", "release-manifest"),
            "SHA256SUMS.txt": ("checksums", "SHA-256 checksums", "verification", "checksums"),
        }
        assets = []
        for name in required_names:
            item = api_assets[name]
            digest = str(item.get("digest") or "")
            api_sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
            expected_sha = file_sha(checksums_path) if name == "SHA256SUMS.txt" else checksums.get(name)
            if not expected_sha or not HEX64.fullmatch(expected_sha):
                raise SystemExit(f"SHA256SUMS.txt does not bind required asset {name}")
            if api_sha and api_sha != expected_sha:
                raise SystemExit(f"GitHub asset digest mismatch for {name}")
            key, label, platform, kind = definitions[name]
            assets.append({
                "key": key,
                "github_asset_id": item.get("id"),
                "name": name,
                "label": label,
                "platform": platform,
                "kind": kind,
                "download_url": item["browser_download_url"],
                "sha256": expected_sha if args.authorize_public else None,
                "size_bytes": item.get("size") if args.authorize_public else None,
                "enabled": args.authorize_public,
                "github_created_at": item.get("created_at"),
                "github_updated_at": item.get("updated_at"),
            })

    authority_permissions = authority.get("permissions") or {}
    permissions = {
        "public_source_visibility": bool(args.authorize_public and authority_permissions.get("public_source")),
        "direct_package_download": bool(args.authorize_public and authority_permissions.get("direct_installer_download")),
        "offline_beta_testing": bool(args.authorize_public and authority_permissions.get("external_beta_registration")),
        "online_beta_testing": bool(args.authorize_public and authority_permissions.get("external_beta_registration")),
        "sponsorship_listing": bool(args.authorize_public and authority_permissions.get("sponsor_registration")),
        "production_use": False,
    }
    license_record = authority.get("license") or {}
    approval = authority.get("owner_approval") or {}
    catalog = {
        "schema": "catalyst-nexus-aurion-beta-release/0.2.1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release_set": {
            "status": "published" if args.authorize_public else "pending-authority",
            "channel": "alpha",
            "release_repository": args.repository,
            "release_tag": args.tag,
            "launcher_version": "0.2.1",
            "launcher_commit_sha": launcher_commit if args.authorize_public else None,
            "github_release_id": release_api.get("id"),
            "release_url": f"https://github.com/{args.repository}/releases/tag/{quote(args.tag, safe='')}",
            "published_at": release_api.get("published_at") if args.authorize_public else None,
            "package_built_at": manifest.get("built_at") if args.authorize_public else None,
            "manifest_sha256": manifest_sha if args.authorize_public else None,
            "public_distribution_authorized": args.authorize_public,
            "terms_version": TERMS_VERSION,
            "terms_sha256": TERMS_SHA,
            "permissions": permissions,
            "license_id": license_record.get("id") if args.authorize_public else "Catalyst-Nexus-AURION-External-Beta-Evaluation-License-0.2.1",
            "license_url": f"https://github.com/{args.repository}/blob/{quote(args.tag, safe='')}/LICENSE.txt" if args.authorize_public else None,
            "license_sha256": license_sha if args.authorize_public else None,
            "approval_references": {"owner_release_approval": approval.get("approval_reference") if args.authorize_public else None},
        },
        "components": COMPONENTS,
        "assets": assets,
    }
    catalog["catalog_sha256"] = canonical_digest(catalog)
    Path(args.output).write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
