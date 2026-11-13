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

@pytest.fixture(autouse=True)
def windows_update_contract(monkeypatch):
    monkeypatch.setattr(updates,'update_target',lambda:'windows')
    monkeypatch.setattr('update_ui.WINDOWS',True)

def release(version='1.17.0', prerelease=False, installed=True):
    filename=f'Cadence-{version}-'+('Setup.exe' if installed else 'Windows.zip')
    return dict(tag_name='v'+version,prerelease=prerelease,draft=False,assets=[
        dict(name=filename,size=len(DATA),state='uploaded',digest='sha256:'+DIGEST),
        dict(name=f'Cadence-{version}-sha256.json',size=100,state='uploaded')])

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

@pytest.mark.parametrize('url', ['http://github.com/a','https://evil.invalid/a','https://github.com.evil.invalid/a','https://x@github.com/a','file:///C:/evil','https://github.com:123/a'])
def test_reject_untrusted_urls(url):
    with pytest.raises(ValueError): updates.checked_url(url)

def test_portable_uses_only_zip():
    assert chosen(False).filename.endswith('Windows.zip')
    assert updates.select_release([release(installed=True)],'1.16.0',False) is None

def test_verified_download(tmp_path):
    item=chosen(); values=[]
    with patch.object(updates,'read_json',return_value={item.filename:DIGEST}), patch.object(updates,'open_url',return_value=io.BytesIO(DATA)):
        path,digest=updates.download(item,tmp_path,threading.Event(),values.append)
    assert path.read_bytes()==DATA and digest==DIGEST and values[-1]==100
    updates.verify_package(path,digest)
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError): updates.verify_package(path,digest)

@pytest.mark.parametrize('payload',[b'',DATA[:-1],DATA+b'overflow',b'x'*len(DATA)])
def test_bad_download_never_committed(tmp_path,payload):
    item=chosen()
    with patch.object(updates,'read_json',return_value={item.filename:DIGEST}), patch.object(updates,'open_url',return_value=io.BytesIO(payload)):
        with pytest.raises(ValueError): updates.download(item,tmp_path,threading.Event(),lambda value:None)
    assert not list(tmp_path.iterdir())

def test_cancelled_download(tmp_path):
    item=chosen(); event=threading.Event()
    with patch.object(updates,'read_json',return_value={item.filename:DIGEST}), patch.object(updates,'open_url',return_value=io.BytesIO(DATA)):
        with pytest.raises(updates.UpdateCancelled): updates.download(item,tmp_path,event,lambda value:event.set())
    assert not list(tmp_path.iterdir())

def test_mismatching_manifest():
    item=chosen()
    with patch.object(updates,'read_json',return_value={item.filename:'0'*64}):
        with pytest.raises(ValueError): updates.package_hash(item)

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
    assert data['auto_update_check'] and not data['update_previews']
    data.update(auto_update_check=False,update_previews=True)
    assert validate(data,{})['auto_update_check'] is False
    assert validate(data,{})['update_previews'] is True

def fake_window(gui):
    from PySide6.QtCore import QSettings,QTimer
    from PySide6.QtWidgets import QWidget
    window=QWidget(); window.preferences={'auto_update_check':True,'update_previews':False}
    window.settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,'CadenceTest','Updates')
    window.job=None; window.timer=QTimer(); window.confirm_discard=lambda:True
    return window

def test_download_needs_consent(gui):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); manager.pending=chosen()
    with patch('update_ui.ConfirmationDialog.exec',return_value=2),patch.object(manager,'run') as start:
        manager.offer_pending(); start.assert_not_called()

def test_install_requires_consent_and_save(gui,tmp_path):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); manager.installed=True
    path=tmp_path/'Setup.exe'; path.write_bytes(DATA)
    with patch('update_ui.ConfirmationDialog.exec',return_value=2),patch('update_ui.launch_installer') as launch:
        manager.install_offer(path,DIGEST); launch.assert_not_called()
    window.confirm_discard=lambda:False
    with patch('update_ui.ConfirmationDialog.exec',return_value=1),patch('update_ui.launch_installer') as launch:
        manager.install_offer(path,DIGEST); launch.assert_not_called()

def test_portable_never_runs_installer(gui,tmp_path):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); manager.installed=False
    with patch('update_ui.QMessageBox.information'),patch('update_ui.QDesktopServices.openUrl') as folder,patch('update_ui.launch_installer') as launch:
        manager.install_offer(tmp_path/'Windows.zip',DIGEST)
        launch.assert_not_called(); folder.assert_called_once()

def test_automatic_disabled_no_network(gui):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); window.preferences['auto_update_check']=False
    with patch.object(manager,'run') as start:
        manager.check_now(False); start.assert_not_called()

def test_wait_while_playing(gui):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); manager.pending=chosen(); window.timer.start(100)
    with patch('update_ui.ConfirmationDialog.exec') as prompt:
        manager.offer_pending(); prompt.assert_not_called()
    manager.stop(); window.timer.stop()

def test_download_completion_does_not_cancel(gui,tmp_path):
    from update_ui import UpdateManager
    from PySide6.QtWidgets import QProgressDialog
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0')
    manager.phase='download'; manager.dialog=QProgressDialog(window)
    manager.dialog.canceled.connect(manager.cancel.set); manager.dialog.show()
    with patch.object(manager,'install_offer') as offer:
        manager.complete((tmp_path/'Windows.zip',DIGEST),'')
        offer.assert_called_once()
    assert not manager.cancel.is_set()

def test_pending_offer_not_overwritten(gui):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); manager.pending=chosen()
    with patch.object(manager,'run') as start:
        manager.check_now(True); start.assert_not_called()

def test_successful_installed_update_keeps_save_guard(gui,tmp_path):
    from update_ui import UpdateManager
    window=fake_window(gui); manager=UpdateManager(window,'1.16.0'); manager.installed=True
    path=tmp_path/'Setup.exe'; path.write_bytes(DATA)
    with patch('update_ui.ConfirmationDialog.exec',return_value=1),patch('update_ui.launch_installer') as launch,patch.object(window,'close') as close:
        manager.install_offer(path,DIGEST)
        launch.assert_called_once(); close.assert_called_once()
    assert window._update_close_approved

def test_english_update_strings(gui):
    import ast,ui_text
    previous=ui_text._language; ui_text._language='en'
    try:
        for node in ast.walk(ast.parse((Path(__file__).resolve().parents[1] / 'update_ui.py').read_text(encoding='utf-8'))):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr' and isinstance(node.args[0],ast.Constant):
                source=node.args[0].value
                assert ui_text.tr(source)!=source or source=='Version',source
    finally: ui_text._language=previous
