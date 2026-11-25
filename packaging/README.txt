Cadence - Packaging

Read docs/BUILD.md and docs/PUBLISHING.md from the repository root.

The build starts from pinned tools and a fresh build directory. release.py consumes the resulting verification.json and rejects changes to sources, test reports or payload files.

Third-party sources and original notices are explicit, hash-verified inputs. No developer parent directory or historical test report is required.

Public update descriptors are signed separately. Windows executables are currently distributed without Authenticode signing.
