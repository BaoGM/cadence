# SignPath application draft

Status: not submitted. Official eligibility criteria and the application form were reviewed at https://signpath.org/terms and https://signpath.org/apply on 2026-11-12. Recheck them before submission.

- Project: Cadence, Windows video review and annotation.
- Purpose: a free and open-source application developed for practical animation review needs that available paid tools did not fully meet in the maintainer's workflow.
- Code license: GPL-3.0-only; unchanged official text in LICENSE and COPYING.txt.
- Owner and public maintainer: BaoGM, https://github.com/BaoGM. Copyright (C) 2026 Cadence contributors confirmed by the project owner.
- Repository and project home: https://github.com/BaoGM/cadence. Private security reports: https://github.com/BaoGM/cadence/security/advisories/new. No separate public website is claimed.
- Logo: GPL-3.0-only, redistribution and modification authorised by the project owner.
- Governance: BaoGM acts as committer, reviewer and release approver; acceptance of this arrangement is SignPath's decision. The maintainer confirms that multi-factor authentication is enabled on the GitHub account.
- Build: Python/Qt application and C++ DLL, pinned dependencies, unsigned Windows workflow, source and binary provenance checks.
- Third-party inventory: THIRD_PARTY.md, original notices and hash-checked corresponding source bundle. Qt/PyAV/FFmpeg source rebuild and Microsoft runtime eligibility require final review.
- Sensitive functions: user-requested screen/audio/input capture, local 3D startup connectors, authenticated loopback synchronisation, media parsing, file associations and administrator installation in Program Files.
- Privacy and signing policies: PRIVACY.md and CODE_SIGNING_POLICY.md.
- Representative release: https://github.com/BaoGM/cadence/releases/tag/v1.15.1, published with the maintainer's explicit approval. It contains the unsigned installer and portable package, corresponding Cadence and third-party sources, checksums and build provenance. The release commit is b2946dc9d735709875a7914f4ca27c6e980876fd.
- Public build: https://github.com/BaoGM/cadence/actions/runs/43111528534. Native compilation, maintained tests and French/English application checks passed. Documentation changes on main after the release do not change its binaries or source archives.
- Installer validation: production installer tested in a fresh offline Windows Sandbox on 2026-11-12, including administrative installation in Program Files, upgrade, reinstallation, French/English application self-tests and uninstallation. See docs/BUILD.md for scope and remaining limits.
- Reputation: recently published project, with no independent coverage, public testimonials or established adoption statistics claimed. Build and release evidence is not a claim of widespread use.

Personal contact details and the completed application remain outside this public repository. The project has not submitted an application, installed the SignPath GitHub integration or configured signing credentials.

Before submission, show the complete final application to the maintainer. Do not submit this draft or install a GitHub integration without explicit approval. The future Foundation certificate does not identify the maintainer personally or Cadence as certificate holder.
