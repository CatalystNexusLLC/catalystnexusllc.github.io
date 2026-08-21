from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from psycopg.types.json import Jsonb

from .db import Database
from .models import BranchProvisionRequest, CheckoutRequest, DeletionRequest, RegistrationRequest
from .release_validation import HEX40, HEX64, ReleaseCatalogError, validate_release_catalog
from .security import InvalidToken, new_csrf_token, new_nonce, sign_payload, verify_payload
from .settings import Settings, get_settings

settings = get_settings()
database = Database(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.open()
    try:
        yield
    finally:
        database.close()


app = FastAPI(
    title="AURION Beta Portal API",
    version="0.2.1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-AURION-CSRF", "X-Release-Sync-Token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _cookie_args(*, max_age: int) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "domain": settings.cookie_domain,
        "path": "/",
        "max_age": max_age,
    }


def _request_evidence(request: Request) -> dict[str, Any]:
    """Create bounded acceptance evidence without retaining raw network identifiers."""

    remote = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:1000]

    def fingerprint(label: str, value: str) -> str:
        return hmac.new(
            settings.session_secret.encode("utf-8"),
            f"{label}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    return {
        "schema": "catalyst-nexus-aurion-consent-evidence/0.2.1",
        "request_id": secrets.token_hex(16),
        "remote_hmac_sha256": fingerprint("remote", remote),
        "user_agent_hmac_sha256": fingerprint("user-agent", user_agent),
        "origin": request.headers.get("origin", "")[:500],
        "host": request.headers.get("host", "")[:255],
        "method": request.method,
        "path": request.url.path,
    }


def _session_from_request(request: Request, *, required: bool = True) -> dict[str, Any] | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub authentication is required")
        return None
    try:
        payload = verify_payload(token, settings.session_secret)
    except InvalidToken as exc:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session is invalid or expired") from exc
        return None
    if payload.get("kind") != "session" or not payload.get("user_id") or not payload.get("csrf"):
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session payload is invalid")
        return None
    return payload


def require_session(request: Request) -> dict[str, Any]:
    payload = _session_from_request(request, required=True)
    assert payload is not None
    return payload


def require_csrf_session(request: Request) -> dict[str, Any]:
    payload = require_session(request)
    supplied = request.headers.get("X-AURION-CSRF", "")
    expected = str(payload.get("csrf", ""))
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token is missing or invalid")
    return payload


Session = Annotated[dict[str, Any], Depends(require_session)]
CsrfSession = Annotated[dict[str, Any], Depends(require_csrf_session)]


def _get_active_user(connection, session: dict[str, Any]) -> dict[str, Any]:
    user = connection.execute(
        """
        SELECT id, github_numeric_id, github_login, avatar_url, status
        FROM portal_users
        WHERE id = %s AND github_numeric_id = %s
        """,
        (session["user_id"], session["github_numeric_id"]),
    ).fetchone()
    if not user or user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user session is no longer active")
    return user


def _registration_record(connection, user_id: UUID | str) -> dict[str, Any] | None:
    registration = connection.execute(
        """
        SELECT id AS registration_id, installation_id, coordination_id,
               participation_kind, test_mode, platform, experience, status,
               signer_name, contact_consent, privacy_consent,
               beta_and_no_warranty, installation_and_operation_responsibility,
               background_services, backup_and_data_loss, release_license,
               electronic_signature, legal_capacity_and_authority,
               terms_version, terms_sha256, privacy_version, registered_at, updated_at
        FROM beta_registrations
        WHERE user_id = %s
        """,
        (user_id,),
    ).fetchone()
    if not registration:
        return None
    branches = connection.execute(
        """
        SELECT service_role, repository, branch_name, base_tag, base_commit,
               status, requested_at, provisioned_at
        FROM branch_enrollments
        WHERE registration_id = %s
        ORDER BY service_role
        """,
        (registration["registration_id"],),
    ).fetchall()
    registration["branches"] = list(branches)
    return registration


def _current_component_lock(connection) -> dict[str, dict[str, Any]]:
    release = connection.execute(
        """
        SELECT id
        FROM release_sets
        WHERE release_repository = %s
        ORDER BY public_distribution_authorized DESC,
                 published_at DESC NULLS LAST,
                 synced_at DESC
        LIMIT 1
        """,
        (settings.release_repository,),
    ).fetchone()
    if not release:
        return {item["service_role"]: dict(item) for item in settings.components}
    rows = connection.execute(
        """
        SELECT service_role, repository, version, tag, commit_sha
        FROM release_components
        WHERE release_set_id = %s
        """,
        (release["id"],),
    ).fetchall()
    return {row["service_role"]: dict(row) for row in rows}


def _current_release_lock(connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT release_repository, release_tag, launcher_version,
               launcher_commit_sha, public_distribution_authorized,
               catalog_sha256, package_built_at, published_at
        FROM release_sets
        WHERE release_repository = %s
        ORDER BY public_distribution_authorized DESC,
                 published_at DESC NULLS LAST,
                 synced_at DESC
        LIMIT 1
        """,
        (settings.release_repository,),
    ).fetchone()
    if row:
        return dict(row)
    return {
        "release_repository": settings.release_repository,
        "release_tag": settings.launcher_tag,
        "launcher_version": settings.launcher_version,
        "launcher_commit_sha": settings.launcher_commit_sha,
        "public_distribution_authorized": False,
        "catalog_sha256": None,
        "package_built_at": None,
        "published_at": None,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    with database.connection() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"ok": True, "service": "aurion-beta-portal-api", "time": datetime.now(timezone.utc)}


@app.get("/auth/github/start")
def github_start() -> Response:
    now = int(time.time())
    state_payload = {
        "kind": "oauth-state",
        "nonce": new_nonce(),
        "iat": now,
        "exp": now + settings.oauth_state_ttl_seconds,
    }
    signed_state = sign_payload(state_payload, settings.session_secret)
    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.github_callback_url,
            "scope": "read:user",
            "state": signed_state,
            "allow_signup": "true",
        }
    )
    response = RedirectResponse(f"{settings.github_authorize_url}?{query}", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.oauth_state_cookie_name,
        signed_state,
        **_cookie_args(max_age=settings.oauth_state_ttl_seconds),
    )
    return response


@app.get("/auth/github/callback")
async def github_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"GitHub authorization failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub callback is missing code or state")
    cookie_state = request.cookies.get(settings.oauth_state_cookie_name, "")
    if not cookie_state or not hmac.compare_digest(cookie_state, state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state does not match")
    try:
        state_payload = verify_payload(state, settings.session_secret)
    except InvalidToken as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state is invalid or expired") from exc
    if state_payload.get("kind") != "oauth-state":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state type is invalid")

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        token_response = await client.post(
            settings.github_token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_callback_url,
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub did not return an access token")
        user_response = await client.get(
            settings.github_user_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "CatalystNexusLLC-AURION-Beta-Portal",
            },
        )
        user_response.raise_for_status()
        github_user = user_response.json()

    github_numeric_id = github_user.get("id")
    github_login = github_user.get("login")
    avatar_url = github_user.get("avatar_url")
    if not isinstance(github_numeric_id, int) or github_numeric_id <= 0 or not isinstance(github_login, str):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub user response is missing immutable identity fields")

    with database.connection() as connection, connection.transaction():
        user = connection.execute(
            """
            INSERT INTO portal_users (github_numeric_id, github_login, avatar_url, last_authenticated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (github_numeric_id) DO UPDATE
            SET github_login = EXCLUDED.github_login,
                avatar_url = EXCLUDED.avatar_url,
                last_authenticated_at = now(),
                status = CASE WHEN portal_users.status = 'deleted' THEN portal_users.status ELSE 'active' END
            RETURNING id, github_numeric_id, github_login, avatar_url, status
            """,
            (github_numeric_id, github_login, avatar_url),
        ).fetchone()
        if user["status"] != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="this beta identity is not active")
        connection.execute(
            "INSERT INTO github_login_history (user_id, github_login) VALUES (%s, %s)",
            (user["id"], github_login),
        )
        connection.execute(
            """
            INSERT INTO audit_events (actor_type, actor_id, action, object_type, object_id, metadata)
            VALUES ('user', %s, 'github-authenticated', 'portal-user', %s, %s)
            """,
            (str(github_numeric_id), str(user["id"]), Jsonb({"login": github_login})),
        )

    now = int(time.time())
    session_payload = {
        "kind": "session",
        "user_id": str(user["id"]),
        "github_numeric_id": github_numeric_id,
        "github_login": github_login,
        "avatar_url": avatar_url,
        "csrf": new_csrf_token(),
        "iat": now,
        "exp": now + settings.session_ttl_seconds,
    }
    session_token = sign_payload(session_payload, settings.session_secret)
    response = RedirectResponse(f"{settings.frontend_url}/#register", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(settings.oauth_state_cookie_name, domain=settings.cookie_domain, path="/")
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        **_cookie_args(max_age=settings.session_ttl_seconds),
    )
    return response


@app.get("/api/session")
def session_status(request: Request) -> dict[str, Any]:
    payload = _session_from_request(request, required=False)
    if not payload:
        return {"authenticated": False}
    with database.connection() as connection:
        user = connection.execute(
            """
            SELECT id, github_numeric_id, github_login, avatar_url, status
            FROM portal_users
            WHERE id = %s AND github_numeric_id = %s
            """,
            (payload["user_id"], payload["github_numeric_id"]),
        ).fetchone()
    if not user or user["status"] != "active":
        return {"authenticated": False}
    return {
        "authenticated": True,
        "csrf_token": payload["csrf"],
        "user": {
            "github_numeric_id": user["github_numeric_id"],
            "github_login": user["github_login"],
            "avatar_url": user["avatar_url"],
        },
    }


@app.post("/api/logout")
def logout(_session: CsrfSession) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, domain=settings.cookie_domain, path="/")
    return response


@app.get("/api/releases")
def current_release() -> dict[str, Any]:
    with database.connection() as connection:
        release = connection.execute(
            """
            SELECT catalog
            FROM release_sets
            WHERE release_repository = %s
            ORDER BY public_distribution_authorized DESC,
                     published_at DESC NULLS LAST,
                     synced_at DESC
            LIMIT 1
            """,
            (settings.release_repository,),
        ).fetchone()
    return {"catalog": release["catalog"] if release else None}


@app.post("/api/registrations")
def save_registration(payload: RegistrationRequest, request: Request, session: CsrfSession) -> dict[str, Any]:
    if (
        payload.terms_version != settings.terms_version
        or payload.terms_sha256 != settings.terms_sha256
        or payload.privacy_version != settings.privacy_version
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="terms or privacy version changed; reload the portal and review the current notice",
        )
    evidence = _request_evidence(request)
    with database.connection() as connection, connection.transaction():
        user = _get_active_user(connection, session)
        registration = connection.execute(
            """
            INSERT INTO beta_registrations (
                user_id, participation_kind, test_mode, platform, experience,
                signer_name, contact_consent, privacy_consent,
                beta_and_no_warranty, installation_and_operation_responsibility,
                background_services, backup_and_data_loss, release_license,
                electronic_signature, legal_capacity_and_authority,
                terms_version, terms_sha256, privacy_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET participation_kind = EXCLUDED.participation_kind,
                test_mode = EXCLUDED.test_mode,
                platform = EXCLUDED.platform,
                experience = EXCLUDED.experience,
                signer_name = EXCLUDED.signer_name,
                contact_consent = EXCLUDED.contact_consent,
                privacy_consent = EXCLUDED.privacy_consent,
                beta_and_no_warranty = EXCLUDED.beta_and_no_warranty,
                installation_and_operation_responsibility = EXCLUDED.installation_and_operation_responsibility,
                background_services = EXCLUDED.background_services,
                backup_and_data_loss = EXCLUDED.backup_and_data_loss,
                release_license = EXCLUDED.release_license,
                electronic_signature = EXCLUDED.electronic_signature,
                legal_capacity_and_authority = EXCLUDED.legal_capacity_and_authority,
                terms_version = EXCLUDED.terms_version,
                terms_sha256 = EXCLUDED.terms_sha256,
                privacy_version = EXCLUDED.privacy_version,
                status = 'active',
                updated_at = now()
            RETURNING id, installation_id, coordination_id
            """,
            (
                user["id"],
                payload.participation_kind,
                payload.test_mode,
                payload.platform,
                payload.experience,
                payload.signer_name,
                payload.contact_consent,
                payload.privacy_consent,
                payload.beta_and_no_warranty,
                payload.installation_and_operation_responsibility,
                payload.background_services,
                payload.backup_and_data_loss,
                payload.release_license,
                payload.electronic_signature,
                payload.legal_capacity_and_authority,
                payload.terms_version,
                payload.terms_sha256,
                payload.privacy_version,
            ),
        ).fetchone()

        component_lock = _current_component_lock(connection)
        release_lock = _current_release_lock(connection)
        requested_components = {item.service_role: item for item in payload.requested_components}
        if set(requested_components) != {item["service_role"] for item in settings.components}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="registration must acknowledge the current three-component release lock",
            )
        for component_config in settings.components:
            role = component_config["service_role"]
            locked = component_lock.get(role, component_config)
            requested = requested_components[role]
            expected_commit = locked.get("commit_sha")
            if (
                requested.repository != component_config["repository"]
                or requested.version != (locked.get("version") or component_config["version"])
                or requested.tag != (locked.get("tag") or component_config["tag"])
                or requested.commit_sha != expected_commit
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"registration component lock is stale or invalid for {role}",
                )

        branch_name = f"users/{registration['installation_id']}"
        branch_locks: list[dict[str, Any]] = []
        for component_config in settings.components:
            role = component_config["service_role"]
            component = component_lock.get(role, component_config)
            branch_locks.append(
                {
                    "service_role": role,
                    "repository": component_config["repository"],
                    "tag": component.get("tag") or component_config["tag"],
                    "commit_sha": component.get("commit_sha"),
                }
            )
        branch_locks.append(
            {
                "service_role": "aurion.launcher",
                "repository": release_lock["release_repository"],
                "tag": release_lock["release_tag"],
                "commit_sha": release_lock.get("launcher_commit_sha"),
            }
        )
        for item in branch_locks:
            base_commit = item.get("commit_sha")
            if base_commit is not None and not HEX40.fullmatch(str(base_commit)):
                base_commit = None
            connection.execute(
                """
                INSERT INTO branch_enrollments (
                    registration_id, service_role, repository, branch_name,
                    base_tag, base_commit, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'requested')
                ON CONFLICT (registration_id, repository) DO UPDATE
                SET service_role = EXCLUDED.service_role,
                    branch_name = EXCLUDED.branch_name,
                    status = CASE
                        WHEN branch_enrollments.status = 'provisioned'
                         AND branch_enrollments.base_tag = EXCLUDED.base_tag
                         AND branch_enrollments.base_commit IS NOT DISTINCT FROM EXCLUDED.base_commit
                        THEN 'provisioned'
                        ELSE 'requested'
                    END,
                    provisioned_at = CASE
                        WHEN branch_enrollments.status = 'provisioned'
                         AND branch_enrollments.base_tag = EXCLUDED.base_tag
                         AND branch_enrollments.base_commit IS NOT DISTINCT FROM EXCLUDED.base_commit
                        THEN branch_enrollments.provisioned_at
                        ELSE NULL
                    END,
                    base_tag = EXCLUDED.base_tag,
                    base_commit = EXCLUDED.base_commit,
                    requested_at = now()
                """,
                (
                    registration["id"],
                    item["service_role"],
                    item["repository"],
                    branch_name,
                    item["tag"],
                    base_commit,
                ),
            )

        consent_rows = [
            ("contact", payload.contact_consent, payload.terms_version, payload.terms_sha256),
            ("privacy", payload.privacy_consent, payload.privacy_version, None),
            ("beta-no-warranty", payload.beta_and_no_warranty, payload.terms_version, payload.terms_sha256),
            ("operation-responsibility", payload.installation_and_operation_responsibility, payload.terms_version, payload.terms_sha256),
            ("background-services", payload.background_services, payload.terms_version, payload.terms_sha256),
            ("backup-data-loss", payload.backup_and_data_loss, payload.terms_version, payload.terms_sha256),
            ("release-license", payload.release_license, payload.terms_version, payload.terms_sha256),
            ("electronic-signature", payload.electronic_signature, payload.terms_version, payload.terms_sha256),
            ("legal-capacity-authority", payload.legal_capacity_and_authority, payload.terms_version, payload.terms_sha256),
        ]
        for consent_type, accepted, document_version, document_sha256 in consent_rows:
            connection.execute(
                """
                INSERT INTO consent_records (
                    user_id, registration_id, consent_type, accepted,
                    document_version, document_sha256, evidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user["id"],
                    registration["id"],
                    consent_type,
                    accepted,
                    document_version,
                    document_sha256,
                    Jsonb(evidence),
                ),
            )

        connection.execute(
            """
            INSERT INTO audit_events (actor_type, actor_id, action, object_type, object_id, metadata)
            VALUES ('user', %s, 'beta-registration-saved', 'beta-registration', %s, %s)
            """,
            (
                str(user["github_numeric_id"]),
                str(registration["id"]),
                Jsonb(
                    {
                        "participation_kind": payload.participation_kind,
                        "test_mode": payload.test_mode,
                        "platform": payload.platform,
                        "installation_id": str(registration["installation_id"]),
                        "request_id": evidence["request_id"],
                    }
                ),
            ),
        )
        result = _registration_record(connection, user["id"])
    return {"registration": result}


@app.get("/api/registrations/me")
def get_registration(session: Session) -> dict[str, Any]:
    with database.connection() as connection:
        user = _get_active_user(connection, session)
        registration = _registration_record(connection, user["id"])
    return {"registration": registration}


@app.get("/api/registrations/me/export")
def export_registration_profile(session: Session) -> dict[str, Any]:
    with database.connection() as connection:
        user = _get_active_user(connection, session)
        registration = _registration_record(connection, user["id"])
        if not registration or registration["status"] != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="an active beta registration is required")
        release_lock = _current_release_lock(connection)
        component_lock = _current_component_lock(connection)
    components = []
    for configured in settings.components:
        locked = component_lock.get(configured["service_role"], configured)
        components.append(
            {
                "service_role": configured["service_role"],
                "repository": configured["repository"],
                "version": locked.get("version") or configured["version"],
                "tag": locked.get("tag") or configured["tag"],
                "commit_sha": locked.get("commit_sha"),
            }
        )
    profile = {
        "schema": "catalyst-nexus-aurion-beta-registration-profile/0.2.1",
        "launcher_version": settings.launcher_version,
        "terms_version": settings.terms_version,
        "terms_sha256": settings.terms_sha256,
        "registration_id": str(registration["registration_id"]),
        "installation_id": str(registration["installation_id"]),
        "coordination_id": str(registration["coordination_id"]),
        "signer_name": registration["signer_name"],
        "participation_kind": registration["participation_kind"],
        "test_mode": registration["test_mode"],
        "github": {
            "owner": settings.release_repository.split("/", 1)[0],
            "login": user["github_login"],
            "numeric_id": str(user["github_numeric_id"]),
        },
        "launcher": {
            "repository": release_lock["release_repository"],
            "version": release_lock["launcher_version"],
            "tag": release_lock["release_tag"],
            "commit_sha": release_lock.get("launcher_commit_sha"),
            "catalog_sha256": release_lock.get("catalog_sha256"),
        },
        "components": components,
        "branches": registration["branches"],
        "exported_at": datetime.now(timezone.utc),
    }
    return {"profile": profile}


@app.post("/api/checkouts")
def create_checkout(payload: CheckoutRequest, request: Request, session: CsrfSession) -> dict[str, Any]:
    evidence = _request_evidence(request)
    with database.connection() as connection, connection.transaction():
        user = _get_active_user(connection, session)
        registration = connection.execute(
            """
            SELECT id, installation_id, coordination_id, signer_name,
                   terms_version, terms_sha256, status
            FROM beta_registrations
            WHERE user_id = %s
            """,
            (user["id"],),
        ).fetchone()
        if not registration or registration["status"] != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="an active beta registration is required")

        release_asset = connection.execute(
            """
            SELECT
                rs.id AS release_set_id,
                rs.release_repository,
                rs.release_tag,
                rs.launcher_version,
                rs.launcher_commit_sha,
                rs.status AS release_status,
                rs.published_at,
                rs.package_built_at,
                rs.manifest_sha256,
                rs.terms_version,
                rs.terms_sha256,
                rs.license_id,
                rs.license_url,
                rs.license_sha256,
                rs.owner_release_approval_ref,
                rs.catalog -> 'release_set' -> 'permissions' AS release_permissions,
                rs.catalog_sha256,
                ra.id AS release_asset_id,
                ra.asset_key,
                ra.name AS asset_name,
                ra.download_url,
                ra.sha256 AS asset_sha256,
                ra.size_bytes,
                ra.enabled
            FROM release_sets rs
            JOIN release_assets ra ON ra.release_set_id = rs.id
            WHERE rs.release_repository = %s
              AND rs.release_tag = %s
              AND ra.asset_key = %s
              AND rs.public_distribution_authorized = true
              AND rs.status = 'published'
              AND ra.enabled = true
            """,
            (settings.release_repository, payload.release_tag, payload.asset_key),
        ).fetchone()
        if not release_asset:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="release asset is not authorized for public checkout")

        required_values = [
            release_asset["published_at"],
            release_asset["package_built_at"],
            release_asset["license_url"],
            release_asset["owner_release_approval_ref"],
            release_asset["size_bytes"],
        ]
        if any(value is None for value in required_values):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="release authority record is incomplete")
        for label, value, pattern in (
            ("launcher commit", release_asset["launcher_commit_sha"], HEX40),
            ("release manifest", release_asset["manifest_sha256"], HEX64),
            ("release license", release_asset["license_sha256"], HEX64),
            ("release asset", release_asset["asset_sha256"], HEX64),
            ("terms", release_asset["terms_sha256"], HEX64),
        ):
            if not pattern.fullmatch(str(value or "")):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{label} identity is invalid")
        release_permissions = release_asset["release_permissions"] or {}
        if not isinstance(release_permissions, dict) or release_permissions.get("direct_package_download") is not True:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="release does not grant direct package download")

        components = connection.execute(
            """
            SELECT service_role, repository, version, tag, commit_sha
            FROM release_components
            WHERE release_set_id = %s
            ORDER BY service_role
            """,
            (release_asset["release_set_id"],),
        ).fetchall()
        if len(components) != 3 or any(not HEX40.fullmatch(str(item["commit_sha"] or "")) for item in components):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="release component lock is incomplete")
        branches = connection.execute(
            """
            SELECT service_role, repository, branch_name, base_tag, base_commit, status
            FROM branch_enrollments
            WHERE registration_id = %s
            ORDER BY service_role
            """,
            (registration["id"],),
        ).fetchall()
        if len(branches) != 4:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="registration branch alignment is incomplete")
        expected_by_repository = {item["repository"]: item for item in components}
        expected_by_repository[release_asset["release_repository"]] = {
            "tag": release_asset["release_tag"],
            "commit_sha": release_asset["launcher_commit_sha"],
        }
        expected_branch_name = f"users/{registration['installation_id']}"
        for branch in branches:
            locked = expected_by_repository.get(branch["repository"])
            if (
                locked is None
                or branch["branch_name"] != expected_branch_name
                or branch["base_tag"] != locked["tag"]
                or str(branch["base_commit"] or "").lower() != str(locked["commit_sha"]).lower()
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="registration branches are not aligned to the requested release; update the registration first",
                )

        checkout_id = secrets.token_hex(16)
        checkout_reference = f"AUR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{checkout_id[:10].upper()}"
        checkout = connection.execute(
            """
            INSERT INTO download_checkouts (
                checkout_reference, user_id, registration_id, release_set_id, release_asset_id,
                github_numeric_id_snapshot, login_snapshot, signer_name_snapshot,
                installation_id_snapshot, coordination_id_snapshot,
                release_repository_snapshot, release_tag_snapshot, launcher_commit_snapshot,
                package_built_at_snapshot, published_at_snapshot,
                asset_name_snapshot, asset_url_snapshot, asset_sha256_snapshot, asset_size_snapshot,
                terms_version_snapshot, terms_sha256_snapshot,
                license_id_snapshot, license_url_snapshot, license_sha256_snapshot,
                owner_release_approval_ref_snapshot,
                release_permissions_snapshot,
                components_snapshot, branches_snapshot, catalog_sha256_snapshot
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s,
                %s,
                %s, %s, %s
            )
            RETURNING id AS checkout_id, checkout_reference, requested_at,
                      login_snapshot, release_tag_snapshot,
                      package_built_at_snapshot, published_at_snapshot,
                      asset_name_snapshot, asset_sha256_snapshot
            """,
            (
                checkout_reference,
                user["id"],
                registration["id"],
                release_asset["release_set_id"],
                release_asset["release_asset_id"],
                user["github_numeric_id"],
                user["github_login"],
                registration["signer_name"],
                registration["installation_id"],
                registration["coordination_id"],
                release_asset["release_repository"],
                release_asset["release_tag"],
                release_asset["launcher_commit_sha"],
                release_asset["package_built_at"],
                release_asset["published_at"],
                release_asset["asset_name"],
                release_asset["download_url"],
                release_asset["asset_sha256"],
                release_asset["size_bytes"],
                release_asset["terms_version"],
                release_asset["terms_sha256"],
                release_asset["license_id"],
                release_asset["license_url"],
                release_asset["license_sha256"],
                release_asset["owner_release_approval_ref"],
                Jsonb(release_permissions),
                Jsonb(list(components)),
                Jsonb(list(branches)),
                release_asset["catalog_sha256"],
            ),
        ).fetchone()

        for consent_type, document_version, document_sha256 in (
            ("release-license", release_asset["license_id"], release_asset["license_sha256"]),
            ("integrity-acknowledgement", release_asset["release_tag"], release_asset["manifest_sha256"]),
            ("operation-responsibility", release_asset["terms_version"], release_asset["terms_sha256"]),
            ("backup-data-loss", release_asset["terms_version"], release_asset["terms_sha256"]),
        ):
            connection.execute(
                """
                INSERT INTO consent_records (
                    user_id, registration_id, checkout_id,
                    consent_type, accepted, document_version, document_sha256, evidence
                ) VALUES (%s, %s, %s, %s, true, %s, %s, %s)
                """,
                (
                    user["id"],
                    registration["id"],
                    checkout["checkout_id"],
                    consent_type,
                    document_version,
                    document_sha256,
                    Jsonb(evidence),
                ),
            )

        connection.execute(
            "INSERT INTO download_events (checkout_id, event_type, metadata) VALUES (%s, 'requested', %s), (%s, 'redirect-issued', %s)",
            (checkout["checkout_id"], Jsonb({"request_id": evidence["request_id"]}), checkout["checkout_id"], Jsonb({"request_id": evidence["request_id"]})),
        )
        connection.execute(
            """
            INSERT INTO audit_events (actor_type, actor_id, action, object_type, object_id, metadata)
            VALUES ('user', %s, 'release-checkout-requested', 'download-checkout', %s, %s)
            """,
            (
                str(user["github_numeric_id"]),
                str(checkout["checkout_id"]),
                Jsonb(
                    {
                        "reference": checkout_reference,
                        "asset_key": payload.asset_key,
                        "release_tag": payload.release_tag,
                        "request_id": evidence["request_id"],
                    }
                ),
            ),
        )
    return {"checkout": checkout, "download_url": release_asset["download_url"]}


@app.get("/api/checkouts")
def list_checkouts(session: Session) -> dict[str, Any]:
    with database.connection() as connection:
        user = _get_active_user(connection, session)
        rows = connection.execute(
            """
            SELECT id AS checkout_id, checkout_reference, requested_at,
                   login_snapshot, release_tag_snapshot,
                   package_built_at_snapshot, published_at_snapshot,
                   asset_name_snapshot, asset_sha256_snapshot
            FROM download_checkouts
            WHERE user_id = %s
            ORDER BY requested_at DESC
            LIMIT 200
            """,
            (user["id"],),
        ).fetchall()
    return {"checkouts": list(rows)}


@app.post("/api/data-deletion-requests")
def request_data_deletion(payload: DeletionRequest, session: CsrfSession) -> dict[str, Any]:
    with database.connection() as connection, connection.transaction():
        user = _get_active_user(connection, session)
        deletion = connection.execute(
            """
            INSERT INTO data_deletion_requests (user_id, reason)
            VALUES (%s, %s)
            RETURNING id, requested_at, status
            """,
            (user["id"], payload.reason),
        ).fetchone()
        connection.execute(
            "UPDATE portal_users SET status = 'deletion-requested' WHERE id = %s",
            (user["id"],),
        )
        connection.execute(
            "UPDATE beta_registrations SET status = 'deletion-requested', updated_at = now() WHERE user_id = %s",
            (user["id"],),
        )
        connection.execute(
            """
            INSERT INTO audit_events (actor_type, actor_id, action, object_type, object_id)
            VALUES ('user', %s, 'data-deletion-requested', 'data-deletion-request', %s)
            """,
            (str(user["github_numeric_id"]), str(deletion["id"])),
        )
    return {"deletion_request": deletion}


@app.post("/api/admin/branches/provisioned")
def mark_branches_provisioned(
    payload: BranchProvisionRequest,
    release_sync_token: str | None = Header(default=None, alias="X-Release-Sync-Token"),
) -> dict[str, Any]:
    if not release_sync_token or not hmac.compare_digest(release_sync_token, settings.release_sync_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="branch sync authentication failed")
    expected_repositories = {item["repository"] for item in settings.components} | {settings.release_repository}
    observed_repositories = {item.repository for item in payload.branches}
    if not observed_repositories.issubset(expected_repositories):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="branch update contains an unpinned repository")
    expected_branch = f"users/{payload.installation_id}"
    if any(item.branch_name != expected_branch for item in payload.branches):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="branch name does not match installation identity")

    with database.connection() as connection, connection.transaction():
        registration = connection.execute(
            "SELECT id FROM beta_registrations WHERE installation_id = %s",
            (payload.installation_id,),
        ).fetchone()
        if not registration:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="installation registration was not found")
        updated: list[dict[str, Any]] = []
        for item in payload.branches:
            row = connection.execute(
                """
                UPDATE branch_enrollments
                SET status = %s,
                    base_commit = %s,
                    provisioned_at = CASE WHEN %s = 'provisioned' THEN now() ELSE provisioned_at END
                WHERE registration_id = %s
                  AND repository = %s
                  AND branch_name = %s
                RETURNING repository, branch_name, base_commit, status, provisioned_at
                """,
                (
                    item.status,
                    item.commit_sha.lower(),
                    item.status,
                    registration["id"],
                    item.repository,
                    item.branch_name,
                ),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"branch enrollment does not match: {item.repository}")
            updated.append(row)
        connection.execute(
            """
            INSERT INTO audit_events (actor_type, actor_id, action, object_type, object_id, metadata)
            VALUES ('admin-sync', NULL, 'beta-branches-updated', 'beta-registration', %s, %s)
            """,
            (
                str(registration["id"]),
                Jsonb({"installation_id": payload.installation_id, "repositories": sorted(observed_repositories)}),
            ),
        )
    return {"ok": True, "branches": updated}


@app.post("/api/admin/releases/sync")
def sync_release_catalog(
    catalog: dict[str, Any] = Body(...),
    release_sync_token: str | None = Header(default=None, alias="X-Release-Sync-Token"),
) -> dict[str, Any]:
    if not release_sync_token or not hmac.compare_digest(release_sync_token, settings.release_sync_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="release sync authentication failed")
    try:
        validated = validate_release_catalog(catalog, settings)
    except ReleaseCatalogError as exc:
        with database.connection() as connection, connection.transaction():
            release = catalog.get("release_set") if isinstance(catalog, dict) else {}
            connection.execute(
                """
                INSERT INTO release_sync_runs (
                    release_repository, release_tag, catalog_sha256,
                    public_distribution_authorized, status, detail
                ) VALUES (%s, %s, %s, false, 'rejected', %s)
                """,
                (
                    str((release or {}).get("release_repository") or "unknown")[:200],
                    str((release or {}).get("release_tag") or "unknown")[:100],
                    "0" * 64,
                    str(exc)[:1000],
                ),
            )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    release = validated["release_set"]
    approvals = release.get("approval_references") or {}
    authorized = release.get("public_distribution_authorized") is True
    release_status = "published" if authorized else "pending-authority"
    catalog_sha256 = validated["catalog_sha256"]

    with database.connection() as connection, connection.transaction():
        existing = connection.execute(
            """
            SELECT id, public_distribution_authorized, catalog_sha256
            FROM release_sets
            WHERE release_repository = %s AND release_tag = %s
            """,
            (release["release_repository"], release["release_tag"]),
        ).fetchone()
        if existing and existing["public_distribution_authorized"]:
            if existing["catalog_sha256"] != catalog_sha256:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="an authorized release catalog is immutable; publish a new tag",
                )
            return {"ok": True, "release_set_id": existing["id"], "catalog_sha256": catalog_sha256, "unchanged": True}

        release_set = connection.execute(
            """
            INSERT INTO release_sets (
                release_repository, release_tag, launcher_version, launcher_commit_sha,
                channel, status,
                github_release_id, release_url, published_at, package_built_at,
                manifest_sha256, public_distribution_authorized,
                terms_version, terms_sha256,
                license_id, license_url, license_sha256,
                owner_release_approval_ref,
                catalog_sha256, catalog, synced_at
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s,
                %s, %s, now()
            )
            ON CONFLICT (release_repository, release_tag) DO UPDATE
            SET launcher_version = EXCLUDED.launcher_version,
                launcher_commit_sha = EXCLUDED.launcher_commit_sha,
                channel = EXCLUDED.channel,
                status = EXCLUDED.status,
                github_release_id = EXCLUDED.github_release_id,
                release_url = EXCLUDED.release_url,
                published_at = EXCLUDED.published_at,
                package_built_at = EXCLUDED.package_built_at,
                manifest_sha256 = EXCLUDED.manifest_sha256,
                public_distribution_authorized = EXCLUDED.public_distribution_authorized,
                terms_version = EXCLUDED.terms_version,
                terms_sha256 = EXCLUDED.terms_sha256,
                license_id = EXCLUDED.license_id,
                license_url = EXCLUDED.license_url,
                license_sha256 = EXCLUDED.license_sha256,
                owner_release_approval_ref = EXCLUDED.owner_release_approval_ref,
                catalog_sha256 = EXCLUDED.catalog_sha256,
                catalog = EXCLUDED.catalog,
                synced_at = now()
            RETURNING id
            """,
            (
                release["release_repository"],
                release["release_tag"],
                release["launcher_version"],
                release.get("launcher_commit_sha"),
                release.get("channel", "alpha"),
                release_status,
                release.get("github_release_id"),
                release["release_url"],
                release.get("published_at"),
                release.get("package_built_at"),
                release.get("manifest_sha256"),
                authorized,
                release["terms_version"],
                release["terms_sha256"],
                release["license_id"],
                release.get("license_url"),
                release.get("license_sha256"),
                approvals.get("owner_release_approval"),
                catalog_sha256,
                Jsonb(validated),
            ),
        ).fetchone()

        connection.execute("DELETE FROM release_components WHERE release_set_id = %s", (release_set["id"],))
        connection.execute("DELETE FROM release_assets WHERE release_set_id = %s", (release_set["id"],))
        for component in validated["components"]:
            connection.execute(
                """
                INSERT INTO release_components (
                    release_set_id, service_role, repository, version, tag, commit_sha
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    release_set["id"],
                    component["service_role"],
                    component["repository"],
                    component["version"],
                    component["tag"],
                    component.get("commit_sha"),
                ),
            )
        for asset in validated["assets"]:
            connection.execute(
                """
                INSERT INTO release_assets (
                    release_set_id, asset_key, github_asset_id, name, label,
                    platform, kind, download_url, sha256, size_bytes, enabled,
                    github_created_at, github_updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    release_set["id"],
                    asset["key"],
                    asset.get("github_asset_id"),
                    asset["name"],
                    asset["label"],
                    asset["platform"],
                    asset["kind"],
                    asset["download_url"],
                    asset.get("sha256"),
                    asset.get("size_bytes"),
                    asset.get("enabled") is True,
                    asset.get("github_created_at"),
                    asset.get("github_updated_at"),
                ),
            )
        connection.execute(
            """
            INSERT INTO release_sync_runs (
                release_repository, release_tag, catalog_sha256,
                public_distribution_authorized, status, detail
            ) VALUES (%s, %s, %s, %s, 'accepted', 'catalog synchronized')
            """,
            (release["release_repository"], release["release_tag"], catalog_sha256, authorized),
        )
        connection.execute(
            """
            INSERT INTO audit_events (actor_type, actor_id, action, object_type, object_id, metadata)
            VALUES ('admin-sync', NULL, 'release-catalog-synchronized', 'release-set', %s, %s)
            """,
            (
                str(release_set["id"]),
                Jsonb({"tag": release["release_tag"], "authorized": authorized, "catalog_sha256": catalog_sha256}),
            ),
        )
    return {"ok": True, "release_set_id": release_set["id"], "catalog_sha256": catalog_sha256, "authorized": authorized}
