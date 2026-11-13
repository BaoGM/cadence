# SPDX-License-Identifier: GPL-3.0-only
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from fractions import Fraction


def run(directory):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    blender = Path(os.environ['CADENCE_BLENDER_EXECUTABLE']).resolve(strict=True)
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    os.environ.update(CADENCE_DISABLE_UPDATES='1', CADENCE_LANGUAGE='fr',
        CADENCE_PREFS=str(root / 'preferences.json'), CADENCE_CACHE=str(root / 'cache'),
        CADENCE_SYNC_ENDPOINT=str(root / 'sync.json'), BLENDER_USER_SCRIPTS=str(root / 'blender-scripts'),
        BLENDER_USER_CONFIG=str(root / 'blender-config'), CADENCE_BLENDER_TEST=str(root))

    from PySide6.QtWidgets import QApplication
    from app import MainWindow
    from drawing import DrawingKey, Mark
    from drawing_transfer import build_bundle
    from media import prepare_media
    from sync3d_setup import install_connector

    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    errors = []
    window.error = errors.append
    media = prepare_media(str(Path(os.environ['CADENCE_SMOKE_MEDIA'])))
    window.doc.append_media([media])
    window.refresh()
    link = window.sync3d
    install_connector('blender')
    link.host = 'blender'
    link.set_enabled(True)
    assert link.enabled, errors
    process = None
    report = {'status': 'running', 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    response = None
    messages = []
    original_read = link.read_drawing


    def read_drawing(message):
        messages.append(message)
        original_read(message)


    link.read_drawing = read_drawing


    def wait(predicate, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            application.processEvents()
            if errors:
                raise AssertionError(errors)
            if process and process.poll() is not None:
                raise RuntimeError('Blender exited: ' + str(process.returncode))
            if predicate():
                return
            time.sleep(.01)
        raise TimeoutError('Live Blender test timed out')


    def host(action='state', **values):
        nonlocal response
        identifier = time.monotonic_ns()
        temporary = root / 'request.tmp'
        temporary.write_text(json.dumps(dict(id=identifier, action=action, **values)))
        temporary.replace(root / 'request.json')
        def received():
            nonlocal response
            try:
                response = json.loads((root / 'response.json').read_text())
                return response.get('id') == identifier
            except (OSError, ValueError):
                return False
        wait(received)
        assert response['ok'], response
        return response


    def mark(name):
        report['checks'].append(name)
        print(name, flush=True)


    try:
        with (root / 'blender.log').open('w') as log:
            process = subprocess.Popen([str(blender),
                '--python', str(source / 'tests/blender_fixture.py')],
                env=dict(os.environ), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        wait(lambda: link.metadata is not None, 60)
        report['blender'] = host()
        assert report['blender']['autostart']
        mark('real_blender_startup_and_authenticated_connection')
        wait(lambda: window.doc.state.position == 0)
        host('frame', frame=125)
        wait(lambda: window.doc.state.position == 24)
        mark('blender_to_cadence')
        window.seek(48)
        wait(lambda: link.awaiting is None and link.metadata['frame'] == 149)
        assert host()['frame'] == 149
        mark('cadence_to_blender')
        link.configure('blender', 'receive', 5, True)
        host('frame', frame=137)
        wait(lambda: window.doc.state.position == 41)
        window.seek(60)
        host()
        assert host()['frame'] == 137
        mark('receive_only_and_offset')
        link.configure('blender', 'send', -3, True)
        window.seek(20)
        wait(lambda: link.awaiting is None and link.metadata['frame'] == 124)
        host('frame', frame=180)
        wait(lambda: link.metadata['frame'] == 180)
        assert window.doc.state.position == 20
        mark('send_only')
        link.configure('blender', 'both', 0, True)
        link.rate_decisions.add((id(window.doc), media['id'], '30'))
        host('rate', fps=30)
        host('frame', frame=131)
        wait(lambda: window.doc.state.position == 24)
        window.seek(48)
        wait(lambda: link.awaiting is None and link.metadata['frame'] == 161)
        assert host()['frame'] == 161
        mark('frame_rate_conversion_24_to_30')
        host('rate', fps=24)
        wait(lambda: link.metadata['fps'] == Fraction(24))
        wait(lambda: 'Camera' in link.cameras)
        mark('camera_discovery')
        keys = (DrawingKey(10, 13, (Mark(points=((.1, .2, 1), (.8, .6, 1)), color='#ff6433'),)),
                DrawingKey(16, 20, (Mark(tool='ellipse', points=((.2, .2, 1), (.8, .8, 1)), color='#19ce58'),)))
        for mode in ('native', 'images'):
            path = build_bundle(keys, root / 'drawing_transfers', 'd' * 32, 160, 90,
                Fraction(24), Fraction(24), 101, 0, 'Camera', mode, 2, 2, .7)
            request = mode + '-test'
            link.drawing_request = request
            assert link.send(dict(type='drawing_send', request=request, path=str(path)))
            wait(lambda: any(m.get('request') == request for m in messages), 60)
            assert next(m for m in messages if m.get('request') == request)['ok']
            state = host()
            assert state['objects'] and state['grease_pencil_frames'] > 0 and state['sentinel'], state
            assert all(obj['parent'] == 'Camera' for obj in state['objects'])
            report[mode] = state
            host('save')
            mark(mode + '_drawings_and_onion_skins')
        request = 'remove-test'
        link.drawing_request = request
        assert link.send(dict(type='drawing_remove', request=request, scope='all_cadence'))
        wait(lambda: any(m.get('request') == request for m in messages))
        state = host()
        assert not state['objects'] and state['sentinel']
        mark('drawing_removal_preserves_scene')
        link.stop()
        wait(lambda: link.metadata is None)
        link.set_enabled(True)
        wait(lambda: link.metadata is not None, 10)
        host('frame', frame=115)
        wait(lambda: window.doc.state.position == 14)
        mark('disconnect_and_reconnect')
        report['status'] = 'passed'
    except Exception:
        report.update(status='failed', error=traceback.format_exc(), errors=errors)
        raise
    finally:
        link.stop()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        window.doc.saved_signature = window.doc.signature()
        window.close()
        (root / 'result.json').write_text(json.dumps(report, indent=2))
