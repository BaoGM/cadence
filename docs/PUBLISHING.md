# Publication and rollback

Nothing in this candidate creates a repository, uploads sources, signs code or publishes a Release automatically.

1. Confirm copyright identity, logo licensing statement, public contact and repository owner. Keep the original demonstration video excluded.
2. Complete the secret scan with a dedicated scanner; review all public files and source archives. Review the candidate diff against the audited local snapshot.
3. Obtain explicit approval to connect to the user's GitHub account. Enable two-factor authentication and restrict connector access where possible.
4. Verify official download locations, action versions and full commit pins; validate the fresh Windows runner toolchain. Configure private security reporting.
5. Present the exact public file set, new-history decision, licenses and known limitations. Obtain approval for repository creation and push. Preserve the original local history.
6. Run the unsigned workflow on the approved commit. Review tests, artifact hashes, corresponding sources and clean-machine installation/upgrade/uninstallation.
7. Obtain separate approval before publishing binary artifacts. Never describe unsigned binaries as signed.
8. Finalise the SignPath application from current official requirements and obtain explicit submission approval. Integrate signing only after acceptance and approval to install its GitHub application.

For a faulty release, keep the source tag and its matching source archives accessible. Mark the release as withdrawn, explain the issue and direct users to a verified previous release. Do not replace a binary under an existing checksum or rewrite public history. Keep a project backup before testing an older version against a newer project format.

If a credential is exposed, revoke it first. History cleanup, force pushes and remote deletions require separate approval. Removing a file locally is not credential revocation.
