from __future__ import annotations

import copy
import unittest

from app.release_validation import ReleaseCatalogError, validate_release_catalog
from app.settings import Settings


COMPONENTS = (
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
)


class ReleaseCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            database_url="postgresql://example",
            github_client_id="client",
            github_client_secret="secret",
            github_callback_url="https://api.example.test/auth/github/callback",
            frontend_url="https://example.test",
            allowed_origins=("https://example.test",),
            session_secret="s" * 64,
            release_sync_token="t" * 64,
            session_cookie_name="session",
            oauth_state_cookie_name="oauth",
            cookie_secure=True,
            cookie_samesite="lax",
            cookie_domain=None,
            session_ttl_seconds=3600,
            oauth_state_ttl_seconds=600,
            release_repository="CatalystNexusLLC/aurion_beta_launcher",
            launcher_version="0.2.1",
            launcher_tag="v0.2.1",
            launcher_commit_sha=None,
            terms_version="AURION-BETA-TERMS-0.2.1",
            terms_sha256="2bbbea4db70594425ddf95560c85b4c2ad8bbb35b533eee87ec07e8f67d2b317",
            privacy_version="AURION-PRIVACY-0.2.1",
            components=COMPONENTS,
        )
        self.catalog = {
            "schema": "catalyst-nexus-aurion-beta-release/0.2.1",
            "generated_at": None,
            "release_set": {
                "status": "pending-authority",
                "channel": "alpha",
                "release_repository": "CatalystNexusLLC/aurion_beta_launcher",
                "release_tag": "v0.2.1",
                "launcher_version": "0.2.1",
                "launcher_commit_sha": None,
                "release_url": "https://github.com/CatalystNexusLLC/aurion_beta_launcher/releases/tag/v0.2.1",
                "published_at": None,
                "package_built_at": None,
                "manifest_sha256": None,
                "public_distribution_authorized": False,
                "terms_version": self.settings.terms_version,
                "terms_sha256": self.settings.terms_sha256,
                "permissions": {
                    "public_source_visibility": True,
                    "direct_package_download": False,
                    "offline_beta_testing": False,
                    "online_beta_testing": False,
                    "sponsorship_listing": False,
                    "production_use": False,
                },
                "license_id": "PENDING-PUBLIC-BETA-LICENSE",
                "license_url": None,
                "license_sha256": None,
                "approval_references": {"owner_release_approval": None},
            },
            "components": [dict(item, commit_sha=None) for item in COMPONENTS],
            "assets": [
                {
                    "key": "complete",
                    "name": "CatalystNexus_AURION_Beta_Launcher_v0.2.1.zip",
                    "label": "Complete launcher release",
                    "platform": "windows-macos-linux",
                    "kind": "complete-release",
                    "download_url": "https://github.com/CatalystNexusLLC/aurion_beta_launcher/releases/download/v0.2.1/CatalystNexus_AURION_Beta_Launcher_v0.2.1.zip",
                    "sha256": None,
                    "size_bytes": None,
                    "enabled": False,
                }
            ],
        }

    def test_pending_catalog_is_valid_but_not_enabled(self) -> None:
        validated = validate_release_catalog(copy.deepcopy(self.catalog), self.settings)
        self.assertRegex(validated["catalog_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(validated["release_set"]["public_distribution_authorized"])
        self.assertTrue(validated["release_set"]["permissions"]["public_source_visibility"])

    def test_wrong_release_repository_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["release_set"]["release_repository"] = "someone/else"
        with self.assertRaises(ReleaseCatalogError):
            validate_release_catalog(catalog, self.settings)

    def test_authorized_catalog_requires_owner_approval(self) -> None:
        catalog = self._authorized_catalog()
        catalog["release_set"]["approval_references"]["owner_release_approval"] = None
        with self.assertRaisesRegex(ReleaseCatalogError, "owner release approval"):
            validate_release_catalog(catalog, self.settings)

    def test_authorized_catalog_requires_launcher_commit(self) -> None:
        catalog = self._authorized_catalog()
        catalog["release_set"]["launcher_commit_sha"] = None
        with self.assertRaisesRegex(ReleaseCatalogError, "launcher commit"):
            validate_release_catalog(catalog, self.settings)

    def test_authorized_catalog_requires_exact_component_commits(self) -> None:
        catalog = self._authorized_catalog()
        catalog["components"][1]["commit_sha"] = None
        with self.assertRaises(ReleaseCatalogError):
            validate_release_catalog(catalog, self.settings)

    def test_fully_authorized_catalog_is_valid(self) -> None:
        validated = validate_release_catalog(self._authorized_catalog(), self.settings)
        self.assertTrue(validated["release_set"]["public_distribution_authorized"])
        self.assertTrue(validated["assets"][0]["enabled"])

    def _authorized_catalog(self) -> dict:
        catalog = copy.deepcopy(self.catalog)
        release = catalog["release_set"]
        release.update(
            {
                "status": "published",
                "launcher_commit_sha": "d" * 40,
                "published_at": "2026-08-20T18:00:00Z",
                "package_built_at": "2026-08-20T17:00:00Z",
                "manifest_sha256": "a" * 64,
                "public_distribution_authorized": True,
                "permissions": {
                    "public_source_visibility": True,
                    "direct_package_download": True,
                    "offline_beta_testing": True,
                    "online_beta_testing": True,
                    "sponsorship_listing": True,
                    "production_use": False,
                },
                "license_id": "CATALYST-AURION-BETA-0.2.1",
                "license_url": "https://github.com/CatalystNexusLLC/aurion_beta_launcher/blob/v0.2.1/LICENSE.txt",
                "license_sha256": "b" * 64,
                "approval_references": {"owner_release_approval": "release-authority:2026-08-20"},
            }
        )
        for index, component in enumerate(catalog["components"]):
            component["commit_sha"] = format(index + 1, "040x")
        catalog["assets"][0].update({"enabled": True, "sha256": "c" * 64, "size_bytes": 12345})
        return catalog


if __name__ == "__main__":
    unittest.main()
