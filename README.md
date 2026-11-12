# Cadence

Cadence is a Windows video review and annotation application for animation. Its interface is available in French and English. The application combines Python and Qt with native C++ rendering components.

## Features

- Frame stepping, looping, markers and audio scrubbing.
- Reference sequences with side-by-side, stacked, overlay, difference and wipe comparison.
- Drawing, text, vector shapes, selections and onion skins.
- Video and audio editing, linked tracks, undo and redo.
- Configurable playback and editing workspaces, movable panels and editable shortcuts.
- MP4, MOV, GIF, WAV and MP3 export.
- Screen capture, with optional system audio, microphone and input indicators.
- Optional timeline synchronisation and drawing transfer with Blender and Maya.
- Optional automatic update checks, with confirmation before downloading and installing.

## Installation

Windows 10 or 11, 64-bit. The [1.15.1 Windows preview](https://github.com/BaoGM/cadence/releases/tag/v1.15.1) includes an installer, a portable archive, corresponding sources, checksums and build provenance. It is unsigned and marked as a prerelease. SignPath Foundation acceptance is not claimed; see the [code signing policy](CODE_SIGNING_POLICY.md).

The installer requires administrator permission to install in Program Files. For the portable edition, extract the whole archive and run `Cadence.exe`; keep `_internal` and `Licences` beside it. Third-party source archives accompany full releases but are not needed to run the application.

## Use

Double-click the empty viewer to open media. Use Help > Quick guide for controls. Playback and Editing modes can each have their own panel layout and timeline style. Settings also allow keyboard and mouse bindings to be changed.

The [French guide](assets/guide_fr.txt) and [English guide](assets/guide_en.txt) are included in the application.

## Development

See [BUILD.txt](BUILD.txt), [build and release verification](docs/BUILD.md), and [contribution guidelines](CONTRIBUTING.md). Automated tests use a synthetic video generated from source; personal media and the former demonstration video are excluded.

The 1.15.1 preview was built from commit `b2946dc9d735709875a7914f4ca27c6e980876fd`. Its [Windows build](https://github.com/BaoGM/cadence/actions/runs/43111528534) passed on GitHub Actions, including C++ compilation and French/English application checks. Later documentation changes on main do not change the released binaries or corresponding source archives. Artifacts are unsigned; code signing still requires review and approval. A repeatable build procedure does not imply byte-for-byte identical binaries.

## License

Cadence's original source code and logo are licensed under GPL-3.0-only. See [LICENSE](LICENSE) and [LICENSING.txt](LICENSING.txt). Third-party components and fonts retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md). This includes the obligation to provide corresponding sources when distributing binaries.

Maintained by [BaoGM](https://github.com/BaoGM). Copyright (C) 2026 Cadence contributors.

[Privacy](PRIVACY.md) | [Security](SECURITY.md) | [Code signing](CODE_SIGNING_POLICY.md) | [Uninstallation](docs/UNINSTALL.md)
