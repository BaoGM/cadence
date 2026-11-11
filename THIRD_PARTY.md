# Third-party components

This inventory does not replace the original notices under Licences in the Windows package, or the corresponding source bundle supplied beside it.

| Component | Role | License information |
| --- | --- | --- |
| Python 3.12 | Runtime | PSF license and bundled third-party notices |
| PySide6 / Shiboken6 / Qt 6.12 | Interface and graphics | Qt/PySide LGPL/GPL alternatives, exceptions and third-party component notices; retain the exact bundled notices |
| PyAV 19.0.2 | Video decoding | PyAV BSD terms; bundled FFmpeg libraries have their own terms |
| FFmpeg export build | Encoding and media processing | GPL-enabled build; included codec libraries and their sources are listed in its manifest |
| NumPy 2.5.4 | Array processing | BSD and bundled numerical-library notices |
| PyAudioWPatch | Windows audio capture | MIT and PortAudio notices |
| psutil 7.2.2 | Local 3D process discovery | BSD |
| PyInstaller | Packaging and bootloader | GPL with bootloader exception; preserve the upstream notice |
| Microsoft runtime libraries | Native runtime | Redistributable runtime terms, not GPL; preserve relevant notices |
| Bundled fonts | Drawing text | SIL Open Font License; original OFL files and assets/fonts/sources.json |
| Inno Setup | Installer | Upstream Inno Setup license; preserve notice |

Qt, PyAV and FFmpeg source archives, build recipes and patches are supplied in the third-party source bundle. The release script verifies every input against packaging/third-party.lock.json. Development tools are not necessarily shipped in the application.

The Windows package must retain all notices, Cadence's exact source archive and instructions for accessing the third-party bundle. Do not replace notices with this summary. GPL-3.0-only applies to Cadence's original code, not as a blanket relicensing of these dependencies.

The current source bundles have been hash-checked locally. Complete independent rebuilds of all upstream binaries and SignPath eligibility remain to be verified; in particular, included Microsoft runtime binaries need to be considered in that review.
