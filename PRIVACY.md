# Privacy

Cadence processes media locally and has no analytics or telemetry. This statement describes Cadence's code, not Windows, graphics drivers or connected 3D applications.

## Update checks

Starting with 1.16.0, the packaged application checks the public BaoGM/cadence releases on GitHub at startup, at most once every 24 hours after a successful check. This option is enabled by default and can be disabled in File > Options > Preferences. Prereleases are excluded unless the user enables them. Help also provides a manual check.

These HTTPS requests disclose the network address and a generic Cadence user-agent to GitHub. No media, project, paths, logs, identifiers or preferences are sent. A package is downloaded only after confirmation and its size and SHA-256 are verified. Installed copies ask again before launching the Windows installer. Portable copies offer an archive to extract manually. The downloaded files remain in the local application-data updates directory.

## Local data

Preferences, workspace layouts, recovery state, logs and caches are stored under `%LOCALAPPDATA%/CadenceStudio`. These can contain media paths, project names and error details. Recovery data references source media; it does not copy those videos. Cache cleanup and session recovery are distinct operations.

Projects contain timeline edits, drawings and references to media. Exports and recordings are saved to the location chosen by the user; capture defaults to a temporary Cadence directory. Removing the application does not automatically remove projects, recordings or preferences.

## Optional capture

Screen recording runs when requested. Depending on the selected options, it can include the cursor, mouse clicks, pressed keys, system sound and microphone audio. Check these options before recording sensitive content. No capture upload is performed by Cadence.

## Optional 3D integration

Timeline synchronisation communicates with a local Blender or Maya process using a loopback TCP connection and a session token. The endpoint description is stored locally. Connectors installed in the user's 3D application startup folders check for Cadence and exchange timeline and drawing data when the connection is enabled. Drawing transfers produce local assets used by the 3D scene.

Network shares can be accessed when the user opens media stored there. Build scripts can download development dependencies when explicitly run. Neither action is analytics.

See docs/UNINSTALL.md for connector and local-data removal. Review logs before sharing them.
