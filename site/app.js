"use strict";
const config = window.AURION_PORTAL_CONFIG;
const state = {session: {authenticated: false}, registration: null, catalog: null};
const api = path => `${config.apiBaseUrl.replace(/\/$/, "")}${path}`;
const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };

async function request(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (state.session.csrf_token && !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) {
    headers["X-AURION-CSRF"] = state.session.csrf_token;
  }
  const response = await fetch(api(path), {...options, credentials: "include", headers});
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); detail = body.detail || detail; } catch (_) { /* no-op */ }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function repositoryUrl(repository) { return `https://github.com/${repository}`; }
function releaseAssetUrl(name) { return `https://github.com/${config.releaseRepository}/releases/download/${encodeURIComponent(config.releaseTag)}/${encodeURIComponent(name)}`; }
function shortSha(value) { return value ? `${value.slice(0, 10)}...` : "Set when tagged"; }

function renderRepositories() {
  const container = document.getElementById("repositories");
  container.replaceChildren();
  config.repositories.forEach(item => {
    const article = document.createElement("article");
    article.className = "repo-card";
    const title = document.createElement("h3"); title.textContent = item.name;
    const role = document.createElement("p"); role.textContent = item.role;
    const link = document.createElement("a"); link.href = repositoryUrl(item.repository); link.textContent = item.repository; link.rel = "noopener";
    const dl = document.createElement("dl"); dl.className = "repo-meta";
    [["Version", item.version], ["Tag", item.tag], ["Commit", shortSha(item.commit_sha)]].forEach(([label, value]) => {
      const dt = document.createElement("dt"); dt.textContent = label;
      const dd = document.createElement("dd"); dd.textContent = value;
      dl.append(dt, dd);
    });
    article.append(title, role, link, dl); container.append(article);
  });
}

function effectiveCatalogAssets() {
  const catalog = state.catalog;
  if (!catalog || !catalog.release_set || !catalog.release_set.public_distribution_authorized) return [];
  return Array.isArray(catalog.assets) ? catalog.assets.filter(asset => asset.enabled === true) : [];
}

function renderAssets() {
  const container = document.getElementById("assets");
  container.replaceChildren();
  const catalogAssets = new Map(effectiveCatalogAssets().map(asset => [asset.key, asset]));
  config.assets.forEach(item => {
    const catalogAsset = catalogAssets.get(item.key);
    const article = document.createElement("article"); article.className = "asset-card";
    const title = document.createElement("h3"); title.textContent = item.label;
    const platform = document.createElement("p"); platform.textContent = item.platform;
    const name = document.createElement("code"); name.textContent = item.name;
    const button = document.createElement("button"); button.type = "button"; button.className = "button primary";
    button.textContent = catalogAsset ? "Record checkout and download" : "Awaiting authorized release";
    button.disabled = !catalogAsset;
    if (catalogAsset) button.addEventListener("click", () => checkout({...item, ...catalogAsset}));
    article.append(title, platform, name, button); container.append(article);
  });
}

function setReleaseStatus() {
  const release = state.catalog && state.catalog.release_set;
  const allowed = Boolean(release && release.public_distribution_authorized && release.permissions && release.permissions.direct_package_download);
  const badge = document.getElementById("release-state");
  badge.textContent = allowed ? "Available" : "Pending";
  badge.className = `pill ${allowed ? "ready" : "pending"}`;
  text("release-message", allowed
    ? `Direct GitHub downloads are authorized for ${release.release_tag}. Verify the published SHA-256 before installation.`
    : "Source can be reviewed, but installer buttons remain disabled until the exact tagged package, license, checksums, and owner release approval are published.");
}

async function loadSession() {
  try {
    state.session = await request("/api/session");
  } catch (_) {
    state.session = {authenticated: false};
  }
  const identity = document.getElementById("identity");
  const signIn = document.getElementById("github-signin");
  if (state.session.authenticated) {
    identity.textContent = `Connected as ${state.session.user.github_login} (GitHub numeric ID ${state.session.user.github_numeric_id}).`;
    signIn.textContent = "Reconnect GitHub identity";
    try {
      const result = await request("/api/registrations/me");
      state.registration = result.registration;
      document.getElementById("export-profile").disabled = !state.registration;
      if (state.registration) {
        text("registration-result", `Registration ${state.registration.registration_id}\nInstallation ${state.registration.installation_id}\nCoordination ${state.registration.coordination_id}`);
      }
    } catch (_) { state.registration = null; }
  } else {
    identity.textContent = "Not connected. GitHub sign-in is required before registration and checkout.";
    document.getElementById("export-profile").disabled = true;
  }
}

async function loadRelease() {
  try {
    const result = await request("/api/releases");
    state.catalog = result.catalog;
  } catch (_) {
    try {
      const response = await fetch("releases.json", {cache: "no-store"});
      state.catalog = await response.json();
    } catch (_) { state.catalog = null; }
  }
  setReleaseStatus(); renderAssets();
}

function checked(form, name) { return Boolean(form.elements[name] && form.elements[name].checked); }

async function register(event) {
  event.preventDefault();
  const output = document.getElementById("registration-result");
  if (!state.session.authenticated) { output.textContent = "Connect GitHub before registering."; return; }
  const form = event.currentTarget;
  const payload = {
    participation_kind: form.elements.participation_kind.value,
    test_mode: form.elements.test_mode.value,
    platform: form.elements.platform.value,
    experience: form.elements.experience.value,
    signer_name: form.elements.signer_name.value.trim(),
    contact_consent: checked(form, "contact_consent"),
    privacy_consent: checked(form, "privacy_consent"),
    beta_and_no_warranty: checked(form, "beta_and_no_warranty"),
    installation_and_operation_responsibility: checked(form, "installation_and_operation_responsibility"),
    background_services: checked(form, "background_services"),
    backup_and_data_loss: checked(form, "backup_and_data_loss"),
    release_license: checked(form, "release_license"),
    electronic_signature: checked(form, "electronic_signature"),
    legal_capacity_and_authority: checked(form, "legal_capacity_and_authority"),
    terms_version: config.termsVersion,
    terms_sha256: config.termsSha256,
    privacy_version: config.privacyVersion,
    requested_components: config.repositories.filter(item => item.role !== "aurion.launcher").map(item => ({
      service_role: item.role, repository: item.repository, version: item.version, tag: item.tag, commit_sha: item.commit_sha
    }))
  };
  output.textContent = "Recording registration...";
  try {
    const result = await request("/api/registrations", {method: "POST", body: JSON.stringify(payload)});
    state.registration = result.registration;
    document.getElementById("export-profile").disabled = false;
    output.textContent = `Registration ${state.registration.registration_id}\nInstallation ${state.registration.installation_id}\nCoordination ${state.registration.coordination_id}\nDownload the installer profile before launching setup.`;
  } catch (error) { output.textContent = error.message; }
}

async function exportProfile() {
  if (!state.session.authenticated || !state.registration) return;
  const button = document.getElementById("export-profile");
  button.disabled = true;
  try {
    const result = await request("/api/registrations/me/export");
    const profile = result.profile;
    const blob = new Blob([`${JSON.stringify(profile, null, 2)}\n`], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `AURION-Beta-Registration-${profile.installation_id}.json`;
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  } catch (error) { text("registration-result", error.message); }
  finally { button.disabled = false; }
}

async function checkout(asset) {
  const output = document.getElementById("download-result");
  if (!state.session.authenticated || !state.registration) { output.textContent = "Connect GitHub and complete registration first."; return; }
  const values = ["checkout-license", "checkout-integrity", "checkout-responsibility", "checkout-data-loss"].map(id => document.getElementById(id).checked);
  if (!values.every(Boolean)) { output.textContent = "Accept all four checkout acknowledgements first."; return; }
  output.textContent = "Recording checkout...";
  try {
    const result = await request("/api/checkouts", {method: "POST", body: JSON.stringify({
      release_tag: config.releaseTag,
      asset_key: asset.key,
      license_accepted: true,
      integrity_acknowledged: true,
      operation_responsibility_acknowledged: true,
      data_loss_acknowledged: true
    })});
    output.textContent = `Checkout ${result.checkout.checkout_reference} recorded at ${result.checkout.requested_at}. Opening the exact GitHub Release asset.`;
    window.location.assign(result.download_url || releaseAssetUrl(asset.name));
  } catch (error) { output.textContent = error.message; }
}

document.addEventListener("DOMContentLoaded", async () => {
  renderRepositories(); renderAssets();
  document.getElementById("github-signin").addEventListener("click", () => window.location.assign(api("/auth/github/start")));
  document.getElementById("registration-form").addEventListener("submit", register);
  document.getElementById("export-profile").addEventListener("click", exportProfile);
  await loadSession(); await loadRelease();
});
