# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import io
from pathlib import Path
import threading
from unittest.mock import patch
import pytest

import updates

DATA = b'cadence-package-test'
DIGEST = hashlib.sha256(DATA).hexdigest()

def release(version='1.17.0', prerelease=False, installed=True):
    filename=f'Cadence-{version}-Windows.zip'
    return dict(tag_name='v'+version,prerelease=prerelease,draft=False,assets=[
        dict(name=filename,size=len(DATA),state='uploaded',digest='sha256:'+DIGEST),
        dict(name=f'Cadence-{version}-update.json',size=100,state='uploaded')])

def chosen(installed=True):
    return updates.select_release([release(installed=installed)],'1.16.0',installed)

def test_numeric_version_and_channels():
    entries=[release('1.9.9'),release('1.16.0'),release('1.17.0'),release('1.18.0',True)]
    assert updates.select_release(entries,'1.16.0',True).version=='1.17.0'
    assert updates.select_release(entries,'1.16.0',True,True).version=='1.18.0'
    assert updates.select_release(entries,'2.0.0',True,True) is None

def test_no_drafts_or_incomplete_assets():
    draft=release(); draft['draft']=True
    missing=release(); missing['assets'].pop()
    malformed=release(); malformed['tag_name']='../../malware'
    oversized=release(); oversized['assets'][0]['size']=updates.MAX_PACKAGE+1
    assert updates.select_release([draft,missing,malformed,oversized],'1.16.0',True) is None

def test_studio_channel_is_separate(monkeypatch):
    studio=release('2.0.1',True)
    studio['tag_name'] += '-windows-studio2'
    stable=release('2.1.0')
    entries=[studio,stable,release('1.18.5')]
    monkeypatch.setattr(updates,'read_json',lambda url: entries)
    assert updates.check('2.0.0',False,False) is None
    assert updates.check('2.0.0',False,True).tag == 'v2.0.1-windows-studio2'
    assert updates.select_release([studio],'1.18.5',True,True) is None

@pytest.mark.parametrize('url', ['http://github.com/a','https://evil.invalid/a','https://github.com.evil.invalid/a','https://x@github.com/a','file:///C:/evil','https://github.com:123/a'])
def test_reject_untrusted_urls(url):
    with pytest.raises(ValueError): updates.checked_url(url)

def test_portable_uses_only_zip():
    assert chosen(False).filename.endswith('Windows.zip')
    assert chosen(True).filename==chosen(False).filename

def test_verified_download(tmp_path):
    item=chosen(); values=[]
    with patch.object(updates,'package_descriptor',return_value={'sha256':DIGEST}), patch.object(updates,'open_url',return_value=io.BytesIO(DATA)):
        path,digest=updates.download(item,tmp_path,threading.Event(),values.append)
    assert path.read_bytes()==DATA and digest==DIGEST and values[-1]==100
    updates.verify_package(path,digest)
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError): updates.verify_package(path,digest)

@pytest.mark.parametrize('payload',[b'',DATA[:-1],DATA+b'overflow',b'x'*len(DATA)])
def test_bad_download_never_committed(tmp_path,payload):
    item=chosen()
    with patch.object(updates,'package_descriptor',return_value={'sha256':DIGEST}), patch.object(updates,'open_url',return_value=io.BytesIO(payload)):
        with pytest.raises(ValueError): updates.download(item,tmp_path,threading.Event(),lambda value:None)
    assert not list(tmp_path.iterdir())

def test_cancelled_download(tmp_path):
    item=chosen(); event=threading.Event()
    with patch.object(updates,'package_descriptor',return_value={'sha256':DIGEST}), patch.object(updates,'open_url',return_value=io.BytesIO(DATA)):
        with pytest.raises(updates.UpdateCancelled): updates.download(item,tmp_path,event,lambda value:event.set())
    assert not list(tmp_path.iterdir())

def test_mismatching_manifest():
    item=chosen()
    descriptor=dict(version=item.version,size=item.size,sha256='0'*64,preview=item.prerelease,signature='')
    with patch.object(updates,'read_json',return_value=descriptor),patch('update_store.verify_signature'):
        with pytest.raises(ValueError): updates.package_descriptor(item)

def test_local_installed_marker(tmp_path):
    assert not updates.installed_copy(tmp_path/'Cadence.exe')
    (tmp_path/'uninstall').mkdir(); (tmp_path/'uninstall/unins000.exe').touch()
    assert updates.installed_copy(tmp_path/'Cadence.exe')

@pytest.fixture
def gui():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    return app

def test_preferences_round_trip(gui):
    from preferences import defaults, validate
    data=defaults({})
    assert data['auto_update_check'] and data['update_previews']
    data.update(auto_update_check=False,update_previews=False)
    assert validate(data,{})['auto_update_check'] is False
    assert validate(data,{})['update_previews'] is False

def fake_window(gui):
    from PySide6.QtCore import QSettings,QTimer
    from PySide6.QtWidgets import QWidget
    window=QWidget(); window.preferences={'auto_update_check':True,'update_previews':False}
    window.settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,'CadenceTest','Updates')
    window.job=None; window.timer=QTimer(); window.confirm_discard=lambda:True
    return window

def test_automatic_disabled_no_network(gui):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.18.5'); window.preferences['auto_update_check']=False
    with patch.object(manager,'run') as start:
        manager.check_now(False); start.assert_not_called()

def test_ready_does_not_restart_automatically(gui):
    from PySide6.QtWidgets import QMainWindow
    from update_ui import UpdateManager
    window=QMainWindow(); manager=UpdateManager(window,'1.18.5')
    manager.phase='download'; window.job=None
    with patch('update_ui.spawn') as restart:
        manager.complete('1.18.6',''); restart.assert_not_called()
        window.confirm_discard=lambda:False
        manager.ready_button.click(); restart.assert_not_called()
        window.confirm_discard=lambda:True
        manager.ready_button.click(); restart.assert_called_once()

def test_english_update_strings(gui):
    import ast,ui_text
    previous=ui_text._language; ui_text._language='en'
    try:
        for node in ast.walk(ast.parse(Path('update_ui.py').read_text(encoding='utf-8'))):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr' and isinstance(node.args[0],ast.Constant):
                source=node.args[0].value
                assert ui_text.tr(source)!=source or source in ('Version','Source B'),source
    finally: ui_text._language=previous
