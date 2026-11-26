# Build and release verification

This procedure builds the hybrid Windows application. It has no dependency on a developer's parent project directory. Generated files stay under `.build`, `.deps` and `dist`, which are excluded from the repository.

## Toolchain

Use Python 3.12.14 x64, Qt 6.12.1 MSVC x64, MSVC 14.44.35207 and Windows SDK 10.0.26100.0. Exact Python package versions and Windows wheel hashes, including build/test dependencies, are in requirements-build.lock. Python, Qt and Inno Setup downloads are identified by SHA-256 in packaging/toolchain.lock.json; FFmpeg's binary and archive hashes are in packaging/fetch_ffmpeg.py.

Run packaging/bootstrap_python.ps1 to obtain the verified Windows runtime from Astral's python-build-standalone distribution and create an isolated build environment. Python 3.12.14 has no Windows entry in the actions/python-versions manifest; do not substitute setup-python for this step. On a Windows runner, packaging/bootstrap_windows.ps1 prepares Qt and Inno Setup and verifies the MSVC installation. The pinned Visual Studio 2022 toolset and SDK must be installed separately if absent. The script fails rather than silently substituting another toolset.

For the two pinned OpenSSL DLLs, use the [portable distribution](https://github.com/BaoGM/cadence/releases/download/v2.0.18-windows-studio2/Cadence-2.0.18-Windows.zip) or rebuild from the OpenSSL-Cadence sources and recipe in the third-party bundle. A changed build requires independently verifying the resulting DLLs and updating packaging/windows-runtime.json. For a local build:

```powershell
./packaging/bootstrap_python.ps1
.deps/build-venv/Scripts/python -m pip install --only-binary=:all: --require-hashes -r requirements-build.lock
.deps/build-venv/Scripts/python packaging/fetch_ffmpeg.py
.deps/build-venv/Scripts/python packaging/windows_runtime.py --tls <extracted-portable>/Cadence/_internal-2.0.18
.deps/build-venv/Scripts/python packaging/build_windows.py --msvc-root "C:/path/to/Visual Studio" --qt-root "C:/path/to/Qt"
```

With a portable toolchain, the MSVC root contains `VC/Tools/MSVC/14.44.35207` and optionally `Windows Kits/10`. For an installed Visual Studio toolchain the SDK is taken from WindowsSdkDir or the standard Windows Kits directory.

The build script generates the synthetic eight-second, 24 fps test video, rebuilds the C++ DLL in a fresh directory, runs the maintained headless test list, builds the application and runs its complete self-test in French and English. It isolates preferences and uses software display for these tests. Success produces `.build/verification.json`, binding source file hashes, tool versions, test results and every payload file.

Application tests are grouped under `tests/`. The maintained CI selection is listed in `packaging/headless-tests.json`; packaging checks stay beside the packaging tools. The remaining historical tests are retained for focused regression investigation. They are not all asserted to be current CI tests. GPU performance, capture devices, network shares, Blender and Maya require additional validation on real systems.

## RIFE interpolation on Windows

The public Windows package contains the RIFE 4.6 engine. Prepare its six runtime files in an independent directory and point the CADENCE_RIFE_BUNDLE environment variable to that directory before freezing. Check every file against packaging/rife-runtime.json. The manifest lists the upstream ZIP, its digest and the exact payload. Use the unmodified x64 vcomp140.dll from the MSVC 14.44.35112 redist directory, Microsoft.VC143.OpenMP, for the runtime checked below. Use packaging/fetch_rife.py with --redist to prepare and verify the six files. The engine, model and accompanying notices keep their original licenses. NVIDIA NvOFFRUC is an optional separate installation.

## Distribution inputs

Full packaging requires the matching third-party source and notice bundle. The bundle's complete file manifest and hashes are in packaging/third-party.lock.json. Use the [matching third-party sources](https://github.com/BaoGM/cadence/releases/download/v2.0.18-windows-studio2/Cadence-2.0.18-third-party-sources.zip) and its SHA-256 from the release checksums.

```powershell
.deps/build-venv/Scripts/python packaging/fetch_release_inputs.py --archive "C:/path/to/third-party-sources.zip" --sha256 THE_VERIFIED_ARCHIVE_SHA256
.deps/build-venv/Scripts/python packaging/release.py --dependency-root .deps/release-inputs --compiler "C:/path/to/ISCC.exe"
```

The release script rejects stale test results, changed sources or changed payloads. It produces unsigned installer, portable archive, exact own-source archive and third-party source archive, with hashes and provenance. The own-source archive is also embedded under Licences/Cadence-sources.zip. Keep the third-party source archive available beside the binaries when redistributing.

`packaging/source-files.txt` is an explicit source allowlist, including itself. When adding a source or documentation file, add its relative path there; never add generated files, logs, credentials or media with unverified rights.

## Reproducibility limits

The Windows workflow was validated on a fresh GitHub-hosted windows-2022 runner on 2026-11-11. It verified the pinned toolchain, compiled the native library, ran the maintained tests, built the application, passed its French and English checks, and produced the unsigned packages. The runner image itself is managed by GitHub and can change; tool versions and hashes are therefore checked and recorded for each build.

The build aims at a reconstructible, verifiable result. It does not claim byte-for-byte identity: PE timestamps, compression, upstream wheels and later signatures may differ. Third-party source manifests include upstream recipes and patches; they have not all been independently rebuilt. The original Qt translation binary is retained with its sources and notices.

Installer upgrade/removal must first be tested with the private test identifier, then in a disposable clean Windows environment. Do not run a production installer as an automated test against a developer's existing Windows installation.

The published 1.15.1 installer was additionally verified on 2026-11-12 in a fresh Windows Sandbox (Windows build 26100), with networking disabled. Administrative silent installation used the default Program Files directory. Upgrade from 1.15.0, reinstallation, file associations, Start Menu shortcut, French/English packaged self-tests and uninstallation passed. All 1,238 installed payload files matched the portable release. Preferences, a user project and a modified user file were preserved. This test used a SYSTEM session and software rendering; interactive UAC prompts and hardware graphics were not covered by it. The Sandbox was stopped after verification.

Signing is a separate, approval-gated stage and is not configured yet.
