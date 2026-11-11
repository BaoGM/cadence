# Code signing policy

Status: preparation only. Cadence has not been accepted by SignPath Foundation, and this candidate's binaries are unsigned. No signing service or certificate is currently promised.

If accepted, the required acknowledgement will be:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

The Foundation's certificate identifies SignPath Foundation, not the maintainer personally or a company called Cadence. SignPath decides whether the project and its governance meet its criteria.

The project currently has one maintainer, [BaoGM](https://github.com/BaoGM), who acts as code author/committer, reviewer and release approver. No additional reviewers or team members are claimed. The repository and representative release must be public before the application is submitted.

Only reviewed official Cadence artifacts built from the approved repository commit are eligible. Each production signing request requires manual approval. Upstream third-party binaries must not be signed as Cadence's own work; their treatment must follow the approved SignPath policy.

A signature authenticates the origin and integrity of an official binary. It neither changes nor restricts GPL-3.0-only rights. Anyone may build, modify and redistribute Cadence under that license, including unsigned builds. Forks may sign their binaries using their own certificates, but must not represent them as official Cadence builds signed by SignPath Foundation.

After acceptance, signing of application, installer and uninstaller will be implemented and verified before release. Hashes must be calculated after signing. Signing is deliberately absent from the current unsigned workflow.
