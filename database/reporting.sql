-- Read-only operational reports for the AURION beta portal.

-- Registration identity, terms evidence, and current branch requests.
SELECT
    r.id AS registration_id,
    u.github_numeric_id,
    u.github_login,
    r.signer_name,
    r.installation_id,
    r.coordination_id,
    r.participation_kind,
    r.test_mode,
    r.terms_version,
    r.terms_sha256,
    r.registered_at,
    b.repository,
    b.branch_name,
    b.base_tag,
    b.base_commit,
    b.status AS branch_status
FROM beta_registrations r
JOIN portal_users u ON u.id = r.user_id
LEFT JOIN branch_enrollments b ON b.registration_id = r.id
ORDER BY r.registered_at DESC, b.repository;

-- Version checkout ledger aligned to package build and publication timestamps.
SELECT
    checkout_reference,
    requested_at,
    github_numeric_id_snapshot,
    login_snapshot,
    installation_id_snapshot,
    release_tag_snapshot,
    package_built_at_snapshot,
    published_at_snapshot,
    asset_name_snapshot,
    asset_sha256_snapshot,
    components_snapshot,
    branches_snapshot
FROM beta_checkout_ledger
ORDER BY requested_at DESC;
