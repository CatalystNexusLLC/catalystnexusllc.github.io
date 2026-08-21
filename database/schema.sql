BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS portal_users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    github_numeric_id bigint NOT NULL UNIQUE CHECK (github_numeric_id > 0),
    github_login text NOT NULL,
    avatar_url text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    first_authenticated_at timestamptz NOT NULL DEFAULT now(),
    last_authenticated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS github_login_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
    github_login text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS github_login_history_user_time_idx ON github_login_history (user_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS beta_registrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE REFERENCES portal_users(id) ON DELETE CASCADE,
    installation_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    coordination_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    participation_kind text NOT NULL CHECK (participation_kind IN ('tester', 'sponsor', 'both')),
    test_mode text NOT NULL CHECK (test_mode IN ('offline', 'online', 'both')),
    platform text NOT NULL CHECK (platform IN ('windows', 'macos', 'linux', 'mixed')),
    experience text NOT NULL CHECK (experience IN ('user', 'developer', 'security', 'accessibility', 'sponsor')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'closed', 'deletion-requested')),
    signer_name text NOT NULL CHECK (length(signer_name) BETWEEN 2 AND 120),
    contact_consent boolean NOT NULL DEFAULT false,
    privacy_consent boolean NOT NULL,
    beta_and_no_warranty boolean NOT NULL,
    installation_and_operation_responsibility boolean NOT NULL,
    background_services boolean NOT NULL,
    backup_and_data_loss boolean NOT NULL,
    release_license boolean NOT NULL,
    electronic_signature boolean NOT NULL,
    legal_capacity_and_authority boolean NOT NULL,
    terms_version text NOT NULL,
    terms_sha256 char(64) NOT NULL,
    privacy_version text NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS branch_enrollments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id uuid NOT NULL REFERENCES beta_registrations(id) ON DELETE CASCADE,
    service_role text NOT NULL,
    repository text NOT NULL,
    branch_name text NOT NULL,
    base_tag text NOT NULL,
    base_commit char(40),
    status text NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'provisioned', 'declined', 'retired')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    provisioned_at timestamptz,
    UNIQUE (registration_id, repository),
    UNIQUE (repository, branch_name)
);
CREATE INDEX IF NOT EXISTS branch_enrollments_registration_idx ON branch_enrollments (registration_id, requested_at);

CREATE TABLE IF NOT EXISTS release_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_repository text NOT NULL,
    release_tag text NOT NULL,
    launcher_version text NOT NULL,
    launcher_commit_sha char(40),
    channel text NOT NULL CHECK (channel IN ('alpha', 'beta', 'stable')),
    status text NOT NULL CHECK (status IN ('draft', 'pending-authority', 'published', 'retired')),
    github_release_id bigint,
    release_url text NOT NULL,
    published_at timestamptz,
    package_built_at timestamptz,
    manifest_sha256 char(64),
    public_distribution_authorized boolean NOT NULL DEFAULT false,
    terms_version text NOT NULL,
    terms_sha256 char(64) NOT NULL,
    license_id text NOT NULL,
    license_url text,
    license_sha256 char(64),
    owner_release_approval_ref text,
    catalog_sha256 char(64) NOT NULL,
    catalog jsonb NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (release_repository, release_tag)
);
CREATE INDEX IF NOT EXISTS release_sets_status_time_idx ON release_sets (public_distribution_authorized, published_at DESC NULLS LAST, synced_at DESC);

CREATE TABLE IF NOT EXISTS release_components (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_set_id uuid NOT NULL REFERENCES release_sets(id) ON DELETE CASCADE,
    service_role text NOT NULL,
    repository text NOT NULL,
    version text NOT NULL,
    tag text NOT NULL,
    commit_sha char(40),
    UNIQUE (release_set_id, service_role),
    UNIQUE (release_set_id, repository)
);

CREATE TABLE IF NOT EXISTS release_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_set_id uuid NOT NULL REFERENCES release_sets(id) ON DELETE CASCADE,
    asset_key text NOT NULL,
    github_asset_id bigint,
    name text NOT NULL,
    label text NOT NULL,
    platform text NOT NULL,
    kind text NOT NULL,
    download_url text NOT NULL,
    sha256 char(64),
    size_bytes bigint,
    enabled boolean NOT NULL DEFAULT false,
    github_created_at timestamptz,
    github_updated_at timestamptz,
    UNIQUE (release_set_id, asset_key),
    UNIQUE (release_set_id, name)
);

CREATE TABLE IF NOT EXISTS download_checkouts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    checkout_reference text NOT NULL UNIQUE,
    user_id uuid NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    registration_id uuid NOT NULL REFERENCES beta_registrations(id) ON DELETE RESTRICT,
    release_set_id uuid NOT NULL REFERENCES release_sets(id) ON DELETE RESTRICT,
    release_asset_id uuid NOT NULL REFERENCES release_assets(id) ON DELETE RESTRICT,
    requested_at timestamptz NOT NULL DEFAULT now(),
    github_numeric_id_snapshot bigint NOT NULL,
    login_snapshot text NOT NULL,
    signer_name_snapshot text NOT NULL,
    installation_id_snapshot uuid NOT NULL,
    coordination_id_snapshot uuid NOT NULL,
    release_repository_snapshot text NOT NULL,
    release_tag_snapshot text NOT NULL,
    launcher_commit_snapshot char(40) NOT NULL,
    package_built_at_snapshot timestamptz NOT NULL,
    published_at_snapshot timestamptz NOT NULL,
    asset_name_snapshot text NOT NULL,
    asset_url_snapshot text NOT NULL,
    asset_sha256_snapshot char(64) NOT NULL,
    asset_size_snapshot bigint NOT NULL CHECK (asset_size_snapshot > 0),
    terms_version_snapshot text NOT NULL,
    terms_sha256_snapshot char(64) NOT NULL,
    license_id_snapshot text NOT NULL,
    license_url_snapshot text NOT NULL,
    license_sha256_snapshot char(64) NOT NULL,
    owner_release_approval_ref_snapshot text NOT NULL,
    release_permissions_snapshot jsonb NOT NULL,
    components_snapshot jsonb NOT NULL,
    branches_snapshot jsonb NOT NULL,
    catalog_sha256_snapshot char(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS download_checkouts_user_time_idx ON download_checkouts (user_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS download_checkouts_release_time_idx ON download_checkouts (release_set_id, requested_at DESC);

CREATE TABLE IF NOT EXISTS consent_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    registration_id uuid REFERENCES beta_registrations(id) ON DELETE RESTRICT,
    checkout_id uuid REFERENCES download_checkouts(id) ON DELETE RESTRICT,
    consent_type text NOT NULL CHECK (consent_type IN (
        'contact', 'privacy', 'beta-no-warranty', 'operation-responsibility',
        'background-services', 'backup-data-loss', 'release-license',
        'electronic-signature', 'legal-capacity-authority', 'integrity-acknowledgement'
    )),
    accepted boolean NOT NULL,
    document_version text NOT NULL,
    document_sha256 char(64),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    CHECK (registration_id IS NOT NULL OR checkout_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS consent_records_user_time_idx ON consent_records (user_id, accepted_at DESC);

CREATE TABLE IF NOT EXISTS download_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    checkout_id uuid NOT NULL REFERENCES download_checkouts(id) ON DELETE CASCADE,
    event_type text NOT NULL CHECK (event_type IN ('requested', 'redirect-issued')),
    event_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_at timestamptz NOT NULL DEFAULT now(),
    actor_type text NOT NULL CHECK (actor_type IN ('user', 'admin-sync', 'system')),
    actor_id text,
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_events_time_idx ON audit_events (event_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_object_idx ON audit_events (object_type, object_id, event_at DESC);

CREATE TABLE IF NOT EXISTS data_deletion_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
    requested_at timestamptz NOT NULL DEFAULT now(),
    reason text,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewing', 'completed', 'denied')),
    resolved_at timestamptz,
    resolution_reference text
);
CREATE INDEX IF NOT EXISTS data_deletion_requests_status_idx ON data_deletion_requests (status, requested_at);

CREATE TABLE IF NOT EXISTS release_sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_repository text NOT NULL,
    release_tag text NOT NULL,
    catalog_sha256 char(64) NOT NULL,
    public_distribution_authorized boolean NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL CHECK (status IN ('accepted', 'rejected')),
    detail text
);

CREATE OR REPLACE FUNCTION reject_row_update()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are append-only and cannot be updated', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS download_checkouts_no_update ON download_checkouts;
CREATE TRIGGER download_checkouts_no_update BEFORE UPDATE ON download_checkouts FOR EACH ROW EXECUTE FUNCTION reject_row_update();
DROP TRIGGER IF EXISTS consent_records_no_update ON consent_records;
CREATE TRIGGER consent_records_no_update BEFORE UPDATE ON consent_records FOR EACH ROW EXECUTE FUNCTION reject_row_update();
DROP TRIGGER IF EXISTS download_events_no_update ON download_events;
CREATE TRIGGER download_events_no_update BEFORE UPDATE ON download_events FOR EACH ROW EXECUTE FUNCTION reject_row_update();
DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events FOR EACH ROW EXECUTE FUNCTION reject_row_update();

CREATE OR REPLACE VIEW beta_checkout_ledger AS
SELECT
    c.checkout_reference,
    c.requested_at,
    c.github_numeric_id_snapshot,
    c.login_snapshot,
    c.signer_name_snapshot,
    c.installation_id_snapshot,
    c.release_repository_snapshot,
    c.release_tag_snapshot,
    c.launcher_commit_snapshot,
    c.package_built_at_snapshot,
    c.published_at_snapshot,
    c.asset_name_snapshot,
    c.asset_sha256_snapshot,
    c.terms_version_snapshot,
    c.license_id_snapshot,
    c.release_permissions_snapshot,
    c.components_snapshot,
    c.branches_snapshot
FROM download_checkouts c;

COMMIT;
