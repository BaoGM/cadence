# Uninstalling

For the installed edition, use Windows Settings > Apps > Cadence > Uninstall. For a portable copy, close Cadence and remove its extracted program folder. Neither operation should delete your media, exports or projects.

Preferences, caches and recovery data remain under `%LOCALAPPDATA%/CadenceStudio`. Delete that folder only if you also want to discard these settings and the recovery session. Recordings saved to a temporary folder or another destination are separate files.

## Blender and Maya connectors

Disable synchronisation in Cadence and close the 3D application first. The installer does not remove connectors installed in application-specific user directories.

- Blender: remove only `cadence_timeline_startup.py` from the relevant version's `scripts/startup` directory under `%APPDATA%/Blender Foundation/Blender`.
- Maya: remove only the `cadence_timeline.mod` module file created by Cadence from your Maya user modules directory. Keep all unrelated scripts and modules.
- The shared connector runtime is under `%LOCALAPPDATA%/CadenceStudio/integrations`.

Drawings already transferred into a 3D scene and assets referenced by that scene are separate from the connector. Keep any files required by scenes you want to retain. Use Cadence's drawing-removal command only when you intend to remove Cadence-owned drawings from that scene.
