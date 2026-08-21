window.AURION_PORTAL_CONFIG = Object.freeze({
  apiBaseUrl: "https://api.example.invalid",
  frontendUrl: "https://catalystnexusllc.github.io/aurion_beta_launcher",
  githubOwner: "CatalystNexusLLC",
  releaseRepository: "CatalystNexusLLC/aurion_beta_launcher",
  releaseTag: "v0.2.1",
  launcherVersion: "0.2.1",
  launcherCommitSha: null,
  termsVersion: "AURION-BETA-TERMS-0.2.1",
  termsSha256: "2bbbea4db70594425ddf95560c85b4c2ad8bbb35b533eee87ec07e8f67d2b317",
  privacyVersion: "AURION-PRIVACY-0.2.1",
  publicDistributionAuthorized: false,
  repositories: [
    {role: "aurion.launcher", name: "AURION Beta Launcher", repository: "CatalystNexusLLC/aurion_beta_launcher", version: "0.2.1", tag: "v0.2.1", commit_sha: null},
    {role: "synapse.brain", name: "SYNAPSE Brain", repository: "CatalystNexusLLC/synapse_mcp", version: "2.0.0-alpha", tag: "v2.0.0-alpha", commit_sha: "a5e6a99dc78e5c67ea28682bbaff7fddd8c77146"},
    {role: "aurion.interface", name: "AURION Avatar", repository: "CatalystNexusLLC/aurion_avatar", version: "1.1.0-alpha", tag: "v1.1.0-alpha", commit_sha: "2c8c7d92e767e4ba564a326ac8f1c3e1ad8673e4"},
    {role: "aurion.workers", name: "AURION Arbiter", repository: "CatalystNexusLLC/aurion_arbiter", version: "0.1.0-alpha", tag: "v0.1.0-alpha", commit_sha: "ea950b079e14f4323902bde5ec5c3a3f8cbbcf4a"}
  ],
  assets: [
    {key: "complete", label: "Complete release ZIP", name: "CatalystNexus_AURION_Beta_Launcher_v0.2.1.zip", platform: "Windows, macOS, Linux"},
    {key: "universal", label: "Universal Python launcher", name: "AURION-Beta-Launcher-v0.2.1.pyz", platform: "CPython 3.11-3.14"},
    {key: "checksums", label: "SHA-256 checksums", name: "SHA256SUMS.txt", platform: "Verification"}
  ]
});
