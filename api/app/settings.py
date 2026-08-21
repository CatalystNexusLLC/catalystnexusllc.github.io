from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


_DEFAULT_COMPONENTS = [
    {
        "service_role": "synapse.brain",
        "repository": "CatalystNexusLLC/synapse_mcp",
        "version": "2.0.0-alpha",
        "tag": "v2.0.0-alpha",
    },
    {
        "service_role": "aurion.interface",
        "repository": "CatalystNexusLLC/aurion_avatar",
        "version": "1.1.0-alpha",
        "tag": "v1.1.0-alpha",
    },
    {
        "service_role": "aurion.workers",
        "repository": "CatalystNexusLLC/aurion_arbiter",
        "version": "0.1.0-alpha",
        "tag": "v0.1.0-alpha",
    },
]


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().rstrip("/") for item in os.getenv(name, default).split(",") if item.strip())


def _components() -> tuple[dict[str, Any], ...]:
    raw = os.getenv("AURION_COMPONENTS_JSON", "").strip()
    if not raw:
        return tuple(_DEFAULT_COMPONENTS)
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or len(parsed) != 3:
        raise RuntimeError("AURION_COMPONENTS_JSON must contain the three component records")
    return tuple(dict(item) for item in parsed)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    github_client_id: str
    github_client_secret: str
    github_callback_url: str
    frontend_url: str
    allowed_origins: tuple[str, ...]
    session_secret: str
    release_sync_token: str
    session_cookie_name: str
    oauth_state_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    cookie_domain: str | None
    session_ttl_seconds: int
    oauth_state_ttl_seconds: int
    release_repository: str
    launcher_version: str
    launcher_tag: str
    launcher_commit_sha: str | None
    terms_version: str
    terms_sha256: str
    privacy_version: str
    components: tuple[dict[str, Any], ...]

    @property
    def github_authorize_url(self) -> str:
        return "https://github.com/login/oauth/authorize"

    @property
    def github_token_url(self) -> str:
        return "https://github.com/login/oauth/access_token"

    @property
    def github_user_url(self) -> str:
        return "https://api.github.com/user"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    session_secret = _required("AURION_SESSION_SECRET")
    sync_token = _required("AURION_RELEASE_SYNC_TOKEN")
    if len(session_secret) < 32 or len(sync_token) < 32:
        raise RuntimeError("session and release-sync secrets must be at least 32 characters")

    same_site = os.getenv("AURION_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        raise RuntimeError("AURION_COOKIE_SAMESITE must be lax, strict, or none")

    frontend_url = _required("AURION_FRONTEND_URL").rstrip("/")
    return Settings(
        database_url=_required("AURION_DATABASE_URL"),
        github_client_id=_required("AURION_GITHUB_CLIENT_ID"),
        github_client_secret=_required("AURION_GITHUB_CLIENT_SECRET"),
        github_callback_url=_required("AURION_GITHUB_CALLBACK_URL"),
        frontend_url=frontend_url,
        allowed_origins=_csv("AURION_ALLOWED_ORIGINS", frontend_url),
        session_secret=session_secret,
        release_sync_token=sync_token,
        session_cookie_name=os.getenv("AURION_SESSION_COOKIE", "aurion_beta_session"),
        oauth_state_cookie_name=os.getenv("AURION_OAUTH_STATE_COOKIE", "aurion_beta_oauth_state"),
        cookie_secure=_bool("AURION_COOKIE_SECURE", True),
        cookie_samesite=same_site,
        cookie_domain=os.getenv("AURION_COOKIE_DOMAIN") or None,
        session_ttl_seconds=int(os.getenv("AURION_SESSION_TTL_SECONDS", "43200")),
        oauth_state_ttl_seconds=int(os.getenv("AURION_OAUTH_STATE_TTL_SECONDS", "600")),
        release_repository=os.getenv("AURION_RELEASE_REPOSITORY", "CatalystNexusLLC/aurion_beta_launcher"),
        launcher_version=os.getenv("AURION_LAUNCHER_VERSION", "0.2.1"),
        launcher_tag=os.getenv("AURION_LAUNCHER_TAG", "v0.2.1"),
        launcher_commit_sha=(os.getenv("AURION_LAUNCHER_COMMIT_SHA", "").strip() or None),
        terms_version=os.getenv("AURION_TERMS_VERSION", "AURION-BETA-TERMS-0.2.1"),
        terms_sha256=_required("AURION_TERMS_SHA256"),
        privacy_version=os.getenv("AURION_PRIVACY_VERSION", "AURION-PRIVACY-0.2.1"),
        components=_components(),
    )
