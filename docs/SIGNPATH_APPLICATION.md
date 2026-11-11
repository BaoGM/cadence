# SignPath application draft

Status: not submitted. Official eligibility criteria were reviewed at https://signpath.org/terms on 2026-11-11 and must be checked again before submission.

- Project: Cadence, Windows video review and annotation.
- Code license: GPL-3.0-only; unchanged official text in LICENSE and COPYING.txt.
- Owner and public maintainer: BaoGM, https://github.com/BaoGM. Copyright (C) 2026 Cadence contributors confirmed by the project owner.
- Repository and project home: https://github.com/BaoGM/cadence. Private security reports: https://github.com/BaoGM/cadence/security/advisories/new. No separate public website is claimed.
- Logo: GPL-3.0-only, redistribution and modification authorised by the project owner.
- Governance: BaoGM acts as committer, reviewer and release approver; acceptance of this arrangement is SignPath's decision. The maintainer confirms that multi-factor authentication is enabled on the GitHub account.
- Build: Python/Qt application and C++ DLL, pinned dependencies, unsigned Windows workflow, source and binary provenance checks.
- Third-party inventory: THIRD_PARTY.md, original notices and hash-checked corresponding source bundle. Qt/PyAV/FFmpeg source rebuild and Microsoft runtime eligibility require final review.
- Sensitive functions: user-requested screen/audio/input capture, local 3D startup connectors, authenticated loopback synchronisation, media parsing, file associations and administrator installation in Program Files.
- Privacy and signing policies: PRIVACY.md and CODE_SIGNING_POLICY.md.
- Public workflow: https://github.com/BaoGM/cadence/actions/workflows/windows-unsigned.yml. The unsigned Windows build has passed, including native compilation and French/English application checks. Releases: https://github.com/BaoGM/cadence/releases. The published dependency-only prerelease is not a representative binary release; a validated binary release must be explicitly approved before submission.

Before submission, show the complete final application to the maintainer. Do not submit this draft or install a GitHub integration without explicit approval. The future Foundation certificate does not identify the maintainer personally or Cadence as certificate holder.
