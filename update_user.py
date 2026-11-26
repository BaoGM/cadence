# SPDX-License-Identifier: GPL-3.0-only
import logging
from pathlib import Path
import sys
import tempfile
import threading

from updates import check, download, package_descriptor, UpdateCancelled, version_tuple
from update_desktop import launch_as_desktop_user
from update_store import base_executable, read_state, shared_install, stage, STORE


def prepare_package(base, release, cancel):
    if shared_install(base):
        raise PermissionError('User update requires a writable, per-user installation')
    store = base.parent / STORE
    state = read_state(store)
    if state.get('failed') == release.version:
        return None
    if state.get('pending') == release.version:
        return release.version
    store.mkdir(exist_ok=True)
    manifest = package_descriptor(release)
    with tempfile.TemporaryDirectory(dir=store) as directory:
        path, digest = download(release, directory, cancel, lambda progress: None, manifest)
        return stage(base, release, path, digest, manifest, cancel)


def prepare_requested(version, arguments):
    try:
        probe = len(arguments) == 2 and arguments[0] == '--probe-user-update'
        if not probe and (len(arguments) != 3 or arguments[0] != '--prepare-user-update'
                          or arguments[1] not in ('stable', 'preview')):
            return 1
        base = base_executable()
        if (not getattr(sys, 'frozen', False) or Path(sys.executable).resolve() != base or shared_install(base)):
            return 5
        expected = arguments[-1]
        version_tuple(expected)
        if probe:
            return 0 if read_state(base.parent / STORE).get('pending') == expected else 2
        release = check(version, False, arguments[1] == 'preview')
        if release is None or release.version != expected:
            return 2
        prepared = prepare_package(base, release, threading.Event())
        return 0 if prepared == expected else 2
    except Exception:
        logging.exception('Could not prepare Cadence update as desktop user')
        return 1


def run_user_worker(base, arguments, cancel):
    child = launch_as_desktop_user(base, arguments)
    try:
        while not cancel.is_set():
            try:
                result = child.wait(timeout=0.5)
                break
            except TimeoutError:
                continue
        else:
            # Let the standard-user worker finish its atomic staging operation if Cadence closes.
            raise UpdateCancelled()
    finally:
        child.close()
    if result == 5:
        raise PermissionError('The desktop user cannot update this installation')
    if result not in (0, 2):
        raise OSError('Could not prepare update as desktop user')
    return result == 0


def prepare_as_desktop_user(base, release, previews, cancel):
    channel = 'preview' if previews else 'stable'
    ready = run_user_worker(base, ['--prepare-user-update', channel, release.version], cancel)
    return release.version if ready else None


def prepared_as_desktop_user(base, version, cancel):
    return run_user_worker(base, ['--probe-user-update', version], cancel)
