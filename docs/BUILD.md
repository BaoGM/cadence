# Build and release verification

This procedure builds the hybrid Windows application. It has no dependency on a developer's parent project directory. Generated files stay under `.build`, `.deps` and `dist`, which are excluded from the repository.

## Toolchain

Use Python 3.12.14 x64, Qt 6.12.0 MSVC x64, MSVC 14.44.35207 and Windows SDK 10.0.26100.0. Exact Python package versions and Windows wheel hashes, including build/test dependencies, are in requirements-build.lock. Python, Qt and Inno Setup downloads are identified by SHA-256 in packaging/toolchain.lock.json; FFmpeg's binary and archive hashes are in packaging/fetch_ffmpeg.py.

Run packaging/bootstrap_python.ps1 to obtain the verified Windows runtime from Astral's python-build-standalone distribution and create an isolated build environment. Python 3.12.14 has no Windows entry in the actions/python-versions manifest; do not substitute setup-python for this step. On a Windows runner, packaging/bootstrap_windows.ps1 prepares Qt and Inno Setup and verifies the MSVC installation. The pinned Visual Studio 2022 toolset and SDK must be installed separately if absent. The script fails rather than silently substituting another toolset.

For a local build:

```powershell
./packaging/bootstrap_python.ps1
.deps/build-venv/Scripts/python -m pip install --only-binary=:all: --require-hashes -r requirements-build.lock
.deps/build-venv/Scripts/python packaging/fetch_ffmpeg.py
.deps/build-venv/Scripts/python packaging/build_windows.py --msvc-root "C:/path/to/Visual Studio" --qt-root "C:/path/to/Qt"
```

With a portable toolchain, the MSVC root contains `VC/Tools/MSVC/14.44.35207` and optionally `Windows Kits/10`. For an installed Visual Studio toolchain the SDK is taken from WindowsSdkDir or the standard Windows Kits directory.

The build script generates the synthetic eight-second, 24 fps test video, rebuilds the C++ DLL in a fresh directory, runs the maintained headless test list, builds the application and runs its complete self-test in French and English. It isolates preferences and uses software display for these tests. Success produces `.build/verification.json`, binding source file hashes, tool versions, test results and every payload file.

Application tests are grouped under `tests/`. The maintained CI selection is listed in `packaging/headless-tests.json`; packaging checks stay beside the packaging tools. The remaining historical tests are retained for focused regression investigation. They are not all asserted to be current CI tests. GPU performance, capture devices, network shares, Blender and Maya require additional validation on real systems.

## Distribution inputs

Full packaging requires the matching third-party source and notice bundle. The bundle's complete file manifest and hashes are in packaging/third-party.lock.json. Public hosting is pending; no download URL is invented in this candidate.

```powershell
.deps/build-venv/Scripts/python packaging/fetch_release_inputs.py --archive "C:/path/to/third-party-sources.zip" --sha256 THE_VERIFIED_ARCHIVE_SHA256
.deps/build-venv/Scripts/python packaging/release.py --dependency-root .deps/release-inputs --compiler "C:/path/to/ISCC.exe"
```

The release script rejects stale test results, changed sources or changed payloads. It produces unsigned installer, portable archive, exact own-source archive and third-party source archive, with hashes and provenance. The own-source archive is also embedded under Licences/Cadence-sources.zip. Keep the third-party source archive available beside the binaries when redistributing.

`packaging/source-files.txt` is an explicit source allowlist, including itself. When adding a source or documentation file, add its relative path there; never add generated files, logs, credentials or media with unverified rights.

## Reproducibility limits

The Windows workflow is a local draft pending its first authorised remote run. Action commits, upstream download hashes and Windows Python wheels were verified on 2026-11-11. The windows-2022 inventory lists Visual Studio 2022 and Windows SDK 10.0.26100.0, but does not prove the exact compiler folder and binary revision used here. The first authorised run must verify this and may require installing the pinned toolset. The runner image itself is managed by GitHub and can change; tool versions and hashes are therefore recorded.

The build aims at a reconstructible, verifiable result. It does not claim byte-for-byte identity: PE timestamps, compression, upstream wheels and later signatures may differ. Third-party source manifests include upstream recipes and patches; they have not all been independently rebuilt. The original Qt translation binary is retained with its sources and notices.

Installer upgrade/removal must be tested with the private test identifier before a public release, then on a clean Windows machine. Never use a production install merely as an automated test. Signing is a separate, approval-gated stage and is not configured yet.
