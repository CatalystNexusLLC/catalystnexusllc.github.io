# AURION Beta Portal changelog

## 0.2.1 - 2026-08-20

### Added

- Launcher 0.2.1 release lock and direct GitHub Release checkout model.
- Four-repository registration: launcher, Brain, Avatar, and Arbiter.
- Seven affirmative clickwrap acknowledgements, including electronic signature and legal capacity.
- Signer, terms, privacy, release, branch, and checkout evidence.
- Non-secret installer-profile export.
- Launcher commit and terms identity in release and checkout records.
- Protected participant-branch reporting for up to four repositories.
- Minimal responsive landing page and exact-tag asset cards.

### Changed

- Component locks now use SYNAPSE Brain 2.0.0-alpha, AURION Avatar 1.1.0-alpha, and AURION Arbiter 0.1.0-alpha.
- Release repository is `CatalystNexusLLC/aurion_beta_launcher`.
- Terms SHA-256 is `2bbbea4db70594425ddf95560c85b4c2ad8bbb35b533eee87ec07e8f67d2b317`.
- Direct package buttons remain disabled until the exact public release authority is complete.

### Security

- Browser identity remains separate from Git source publication.
- Provider OAuth tokens are discarded after identity validation.
- Request evidence is bounded and hashed rather than storing raw network identifiers.
- Local assistant content and credentials remain outside the portal database.
