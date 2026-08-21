# AURION Beta Registration and Release Portal 0.2.1

This folder contains the GitHub Pages landing site, GitHub identity flow, FastAPI service, PostgreSQL ledger, release-catalog synchronizer, and protected workflow definitions used by the Catalyst Nexus AURION Assistant Triad Beta Launcher 0.2.1.

## Portal responsibilities

The portal:

- presents the four-repository release lock;
- connects a GitHub identity and stores the immutable numeric account ID separately from the current login;
- records seven affirmative beta acknowledgements, signer name, terms version/hash, privacy version, and UTC evidence;
- creates registration, installation, and coordination UUIDs;
- records four requested `users/<installation-id>` branches;
- exports a non-secret installer profile;
- exposes direct GitHub Release asset checkout only after the release catalog is authorized;
- snapshots asset, license, terms, branch, commit, build, publication, and request timestamps;
- provides data-deletion request handling.

The portal does not receive local assistant prompts, transcripts, model output, memory databases, embeddings, credentials, source replacement content, or ticket worktrees.

## Components

- `site/` - static Pages site and fail-closed release catalog.
- `api/` - FastAPI identity, registration, branch, checkout, and deletion API.
- `database/schema.sql` - PostgreSQL schema and append-only protections.
- `database/reporting.sql` - bounded operations queries.
- `scripts/` - static build, catalog sync, workflow-pin check, and validation.
- `.github/workflows/` - standalone portal examples. The top-level launcher repository also contains root workflows with adjusted paths.

## Local validation

```text
python -m compileall -q api/app api/tests scripts
node --check site/app.js
python scripts/validate_portal.py
python scripts/check_workflow_pins.py
PYTHONPATH=api python -m unittest discover -s api/tests -v
```

## Production configuration

Copy `.env.example` into the deployment secret store rather than committing real values. Use HTTPS, secure cookies, a stable callback URL, an unguessable OAuth state, CSRF protection, PostgreSQL backup/restore tests, protected environments, and minimum-permission GitHub App installation tokens.

Set the exact launcher commit only after `v0.2.1` exists. Keep direct download disabled until the complete release authority, license hash, terms hash, asset hashes/sizes, and final component commits match.

## Distribution boundary

Static source links and GitHub Release URLs are public only when the corresponding repositories and release exist. The starter `site/releases.json` keeps all installer assets disabled. It is replaced by `scripts/sync_release_catalog.py` after the exact tagged release is published and reviewed.

This package does not create remote repositories, Pages deployments, OAuth applications, API hosts, databases, branches, or releases by itself.
