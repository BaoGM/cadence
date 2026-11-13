# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import io
from pathlib import Path
import threading

import pytest

import updates
from association_linux import desktop_entry


def test_linux_releases_require_platform_architecture_and_checksum(monkeypatch):
    monkeypatch.setattr(updates, 'update_target', lambda: 'linux-x86_64')
    def release(version, suffix, checksum=True):
        assets = [dict(name=f'Cadence-{version}-{suffix}', size=100, state='uploaded')]
        if checksum: assets.append(dict(name=f'Cadence-{version}-sha256.json', state='uploaded'))
        return dict(tag_name='v'+version, assets=assets)
    entries = [release('1.20.0', 'Windows.zip'), release('1.21.0', 'Setup.exe'),
               release('1.19.0', 'Linux-aarch64.tar.gz'), release('1.18.0', 'Linux-x86_64.tar.gz', False)]
    assert updates.select_release(entries, '1.16.1', False) is None
    entries.append(release('1.17.0', 'Linux-x86_64.tar.gz'))
    assert updates.select_release(entries, '1.16.1', True).filename == 'Cadence-1.17.0-Linux-x86_64.tar.gz'
    entries[-1]['prerelease'] = True
    assert updates.select_release(entries, '1.16.1', False) is None
    assert updates.select_release(entries, '1.16.1', False, True).version == '1.17.0'


def test_linux_archive_download_and_tamper_detection(monkeypatch, tmp_path):
    data = b'linux-test-archive'; digest = hashlib.sha256(data).hexdigest()
    release = updates.Release('1.17.0', False, 'Cadence-1.17.0-Linux-x86_64.tar.gz', len(data), digest)
    monkeypatch.setattr(updates, 'read_json', lambda *args: {release.filename:digest})
    monkeypatch.setattr(updates, 'open_url', lambda url:io.BytesIO(data))
    path, result = updates.download(release, tmp_path, threading.Event(), lambda value:None)
    assert result == digest and path.read_bytes() == data
    path.write_bytes(b'changed')
    with pytest.raises(ValueError): updates.verify_package(path, digest)


def test_desktop_launcher_escapes_paths_without_shell_expansion():
    entry = desktop_entry('/home/test/A $B`C\\D%f"E/Cadence')
    assert 'Exec="/home/test/A \\\\$B\\\\`C\\\\\\\\D%%f\\\\"E/Cadence" %f\n' in entry
    assert 'application/x-cadence-project;' in entry
    assert 'video/mp4;' in entry
    with pytest.raises(ValueError): desktop_entry('/home/test/Bad\nExec=evil')


def test_wayland_capture_is_rejected(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from capture_x11 import available
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    assert not available()


@pytest.mark.skipif(__import__('sys').platform != 'linux', reason='Linux backend')
def test_x11_capture_command_retains_cursor_region_and_no_overwrite(monkeypatch):
    from capture import capture_args
    monkeypatch.setenv('DISPLAY', ':7')
    args = capture_args((101, 27, 319, 179), 24, False, '/tmp/odd region.mp4')
    assert args[args.index('-f')+1] == 'x11grab'
    assert args[args.index('-i')+1] == ':7'
    assert args[args.index('-grab_x')+1] == '101'
    assert args[args.index('-draw_mouse')+1] == '0'
    assert '-n' in args and 'pad=ceil(iw/2)*2:ceil(ih/2)*2' in args
    with pytest.raises(ValueError): capture_args((-1, 0, 100, 100), 30, True, '/tmp/invalid.mp4')


def test_linux_microphone_does_not_silently_record_output(monkeypatch):
    import capture_audio_linux as audio
    monkeypatch.setattr(audio, 'pulse', lambda *args:'auto_null.monitor' if args == ('get-default-source',)
                        else '[{"name":"auto_null.monitor","monitor_of_sink":0,"monitor_of_sink_name":"auto_null"}]')
    with pytest.raises(RuntimeError, match='microphone'): audio.sources(False, True)
