from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from .settings import Settings


HEX40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
HEX64 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
TAG = re.compile(r"^v[0-9A-Za-z][0-9A-Za-z._-]*$")
PLACEHOLDER = re.compile(r"(?:PENDING|REQUIRED|REPLACE|TBD|TODO|EXAMPLE)", re.IGNORECASE)
CATALOG_SCHEMA = "catalyst-nexus-aurion-beta-release/0.2.1"


class ReleaseCatalogError(ValueError):
    pass


def canonical_catalog_sha256(catalog: dict[str, Any]) -> str:
    normalized = {key: value for key, value in catalog.items() if key != "catalog_sha256"}
    serialized = json.dumps(normalized, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReleaseCatalogError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseCatalogError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReleaseCatalogError(f"{label} must include a timezone")
    return parsed


def validate_release_catalog(catalog: dict[str, Any], settings: Settings) -> dict[str, Any]:
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise ReleaseCatalogError("unexpected release catalog schema")
    release = catalog.get("release_set")
    components = catalog.get("components")
    assets = catalog.get("assets")
    if not isinstance(release, dict) or not isinstance(components, list) or not isinstance(assets, list):
        raise ReleaseCatalogError("catalog release_set, components, and assets are required")
    if release.get("release_repository") != settings.release_repository:
        raise ReleaseCatalogError("release repository does not match the pinned repository")
    if release.get("launcher_version") != settings.launcher_version:
        raise ReleaseCatalogError("launcher version does not match the portal configuration")
    tag = release.get("release_tag")
    if tag != settings.launcher_tag or not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise ReleaseCatalogError("release tag is invalid or is not the pinned launcher tag")
    launcher_commit = release.get("launcher_commit_sha")
    if launcher_commit is not None and not HEX40.fullmatch(str(launcher_commit)):
        raise ReleaseCatalogError("launcher commit must be a full Git SHA")
    expected_release_url = f"https://github.com/{settings.release_repository}/releases/tag/{quote(tag, safe='')}"
    if release.get("release_url") != expected_release_url:
        raise ReleaseCatalogError("release URL is not pinned to the exact GitHub repository and tag")
    if release.get("terms_version") != settings.terms_version or release.get("terms_sha256") != settings.terms_sha256:
        raise ReleaseCatalogError("release terms identity does not match the portal configuration")

    expected_components = {item["service_role"]: item for item in settings.components}
    observed_roles: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise ReleaseCatalogError("component records must be objects")
        role = component.get("service_role")
        expected = expected_components.get(role)
        if expected is None or role in observed_roles:
            raise ReleaseCatalogError("component role set is invalid")
        observed_roles.add(role)
        for field in ("repository", "version", "tag"):
            if component.get(field) != expected[field]:
                raise ReleaseCatalogError(f"{field} mismatch for {role}")
        commit = component.get("commit_sha")
        if commit is not None and not HEX40.fullmatch(str(commit)):
            raise ReleaseCatalogError(f"commit must be a full SHA for {role}")
    if observed_roles != set(expected_components):
        raise ReleaseCatalogError("catalog must contain the three pinned service components")

    exact_prefix = f"https://github.com/{settings.release_repository}/releases/download/{quote(tag, safe='')}/"
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ReleaseCatalogError("asset records must be objects")
        key = asset.get("key")
        name = asset.get("name")
        if not key or key in seen_keys or not name or name in seen_names:
            raise ReleaseCatalogError("asset keys and names must be unique")
        seen_keys.add(str(key))
        seen_names.add(str(name))
        expected_url = exact_prefix + quote(str(name), safe="-._~")
        if asset.get("download_url") != expected_url:
            raise ReleaseCatalogError(f"asset {key} is not pinned to the exact GitHub tag and filename")
        digest = asset.get("sha256")
        if digest is not None and not HEX64.fullmatch(str(digest)):
            raise ReleaseCatalogError(f"asset {key} has an invalid SHA-256")
        size = asset.get("size_bytes")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size <= 0):
            raise ReleaseCatalogError(f"asset {key} has an invalid byte size")

    permissions = release.get("permissions") or {}
    if not isinstance(permissions, dict):
        raise ReleaseCatalogError("release permissions must be an object")
    permission_keys = (
        "public_source_visibility",
        "direct_package_download",
        "offline_beta_testing",
        "online_beta_testing",
        "sponsorship_listing",
        "production_use",
    )
    if any(not isinstance(permissions.get(key, False), bool) for key in permission_keys):
        raise ReleaseCatalogError("release permission values must be booleans")

    approvals = release.get("approval_references") or {}
    if not isinstance(approvals, dict):
        raise ReleaseCatalogError("approval_references must be an object")
    if not release.get("license_id"):
        raise ReleaseCatalogError("release license identity is required")

    authorized = release.get("public_distribution_authorized") is True
    if authorized:
        if release.get("status") != "published":
            raise ReleaseCatalogError("authorized catalog status must be published")
        for key in ("direct_package_download", "offline_beta_testing", "online_beta_testing"):
            if permissions.get(key) is not True:
                raise ReleaseCatalogError(f"authorized catalog must enable {key}")
        if permissions.get("production_use") is True:
            raise ReleaseCatalogError("this beta catalog cannot grant production use")
        published_at = _timestamp(release.get("published_at"), "published_at")
        package_built_at = _timestamp(release.get("package_built_at"), "package_built_at")
        if package_built_at > published_at:
            raise ReleaseCatalogError("package build timestamp cannot be later than GitHub publication")
        if not HEX40.fullmatch(str(launcher_commit or "")):
            raise ReleaseCatalogError("authorized catalog requires the exact launcher commit")
        if settings.launcher_commit_sha and str(launcher_commit).lower() != settings.launcher_commit_sha.lower():
            raise ReleaseCatalogError("launcher commit does not match the configured release commit")
        for name in ("license_id", "license_url"):
            value = release.get(name)
            if not value or PLACEHOLDER.search(str(value)):
                raise ReleaseCatalogError(f"authorized catalog requires a non-placeholder {name}")
        if not str(release["license_url"]).startswith("https://"):
            raise ReleaseCatalogError("authorized catalog requires an immutable HTTPS license URL")
        if not HEX64.fullmatch(str(release.get("manifest_sha256", ""))):
            raise ReleaseCatalogError("authorized catalog requires a manifest SHA-256")
        if not HEX64.fullmatch(str(release.get("license_sha256", ""))):
            raise ReleaseCatalogError("authorized catalog requires a license SHA-256")
        owner_approval = approvals.get("owner_release_approval")
        if not owner_approval or PLACEHOLDER.search(str(owner_approval)):
            raise ReleaseCatalogError("authorized catalog requires a non-placeholder owner release approval reference")
        for component in components:
            if not HEX40.fullmatch(str(component.get("commit_sha", ""))):
                raise ReleaseCatalogError("authorized catalog requires every component commit")
        for asset in assets:
            if asset.get("enabled") is not True:
                raise ReleaseCatalogError("every published portal asset must be explicitly enabled")
            if not HEX64.fullmatch(str(asset.get("sha256", ""))):
                raise ReleaseCatalogError("every enabled asset requires SHA-256")
            if not isinstance(asset.get("size_bytes"), int) or isinstance(asset.get("size_bytes"), bool) or asset["size_bytes"] <= 0:
                raise ReleaseCatalogError("every enabled asset requires byte size")
    else:
        for key in ("direct_package_download", "offline_beta_testing", "online_beta_testing", "sponsorship_listing", "production_use"):
            if permissions.get(key) is True:
                raise ReleaseCatalogError(f"unauthorized catalog cannot enable {key}")
        if any(asset.get("enabled") is not False for asset in assets):
            raise ReleaseCatalogError("unauthorized catalog must keep every asset disabled")

    catalog["catalog_sha256"] = canonical_catalog_sha256(catalog)
    return catalog
