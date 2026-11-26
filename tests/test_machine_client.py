# SPDX-License-Identifier: GPL-3.0-only
import ctypes
from ctypes import wintypes as wt
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from test_updates1160 import gui,fake_window

import update_machine as machine


def verify_own_process_grant():
    from collections import Counter
    from maintenance_identity import grant_service_query,SERVICE_SID
    security=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    ptr=ctypes.c_void_p
    kernel.GetCurrentProcess.restype=wt.HANDLE
    kernel.LocalFree.argtypes=[wt.HLOCAL]
    security.GetSecurityInfo.argtypes=[wt.HANDLE,ctypes.c_int,wt.DWORD,*[ctypes.POINTER(ptr)]*5]
    security.GetAce.argtypes=[ptr,wt.DWORD,ctypes.POINTER(ptr)]
    security.ConvertSidToStringSidW.argtypes=[ptr,ctypes.POINTER(wt.LPWSTR)]
    def entries():
        acl,descriptor=ptr(),ptr()
        assert security.GetSecurityInfo(kernel.GetCurrentProcess(),6,4,None,None,ctypes.byref(acl),None,ctypes.byref(descriptor))==0
        try:
            values=[]
            for index in range(ctypes.c_ushort.from_address(acl.value+4).value):
                ace=ptr(); assert security.GetAce(acl,index,ctypes.byref(ace))
                size=ctypes.c_ushort.from_address(ace.value+2).value
                binary=ctypes.string_at(ace.value,size)
                if binary[0]==0:
                    sid=wt.LPWSTR()
                    assert security.ConvertSidToStringSidW(ace.value+8,ctypes.byref(sid))
                    try: identity=sid.value
                    finally: kernel.LocalFree(ctypes.cast(sid,ptr))
                    values.append((identity,int.from_bytes(binary[4:8],'little'),binary[1]))
                else: values.append(binary)
            return Counter(values)
        finally: kernel.LocalFree(descriptor)
    original=entries(); grant_service_query(); final=entries()
    assert not (original-final)
    assert final-original==Counter({(SERVICE_SID,0x1000,0):1})
    grant_service_query(); assert entries()==final


def test_only_query_limited_right_is_added_on_real_disposable_process():
    test_directory = Path(__file__).resolve().parent
    subprocess.run([sys.executable,'-c','from test_machine_client import verify_own_process_grant;verify_own_process_grant()'],
                   cwd=test_directory.parent, env=dict(os.environ, PYTHONPATH=str(test_directory)),
                   check=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)


def test_known_installation_is_independent_of_environment(monkeypatch):
    fixed=machine.install_paths()
    monkeypatch.setenv('ProgramFiles','D:/Arbitrary')
    assert machine.install_paths()==fixed
    app,watcher=fixed
    assert app.name=='Cadence.exe' and watcher.name=='CadenceRestart.exe'
    assert app.parents[1]==watcher.parents[1] and app.parent.name=='Cadence 2.0'
    assert not machine.configured(Path('Cadence.exe'))


@pytest.fixture
def elevated_portable(gui,tmp_path,monkeypatch):
    import update_ui
    window=fake_window(gui)
    window.settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    manager=update_ui.UpdateManager(window,'2.0.12')
    manager.base=tmp_path/'portable'/'Cadence.exe'
    manager.base.parent.mkdir()
    manager.base.touch()
    monkeypatch.setattr(update_ui.sys,'frozen',True,raising=False)
    monkeypatch.delenv('CADENCE_DISABLE_UPDATES',raising=False)
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:True)
    monkeypatch.setattr(machine,'install_paths',lambda:(tmp_path/'installed'/'Cadence.exe',None))
    monkeypatch.setattr(update_ui,'spawn',lambda *args:pytest.fail('Relaunch inherited elevation'))
    monkeypatch.setattr(update_ui,'prepare_package',lambda *args:pytest.fail('Staging inherited elevation'))
    monkeypatch.setattr(manager,'run',lambda operation:manager.complete(operation(),''))
    try:
        yield manager
    finally:
        manager.stop()
        if manager.ready_button: manager.ready_prompt.close()
        window.close()


@pytest.mark.parametrize('manual',[True,False],ids=['manual','automatic'])
def test_elevated_portable_can_check_without_staging(elevated_portable,monkeypatch,manual):
    import update_ui
    from ui_text import tr
    manager=elevated_portable
    checked=[]; messages=[]
    monkeypatch.setattr(update_ui,'check',lambda version,installed,previews:checked.append((version,previews)))
    monkeypatch.setattr(update_ui.QMessageBox,'information',lambda parent,title,text:messages.append(text))
    manager.start()
    assert manager.check_timer.isActive()
    manager.check_now(manual)
    assert checked==[(manager.version,False)]
    assert messages==([tr('Aucune nouvelle version disponible.')] if manual else [])
    assert float(manager.window.settings.value('updates/last_check',0))>0
    assert list(manager.base.parent.iterdir())==[manager.base]


@pytest.mark.parametrize('can_close',[True,False],ids=['confirmed','window-veto'])
def test_elevated_portable_prepares_and_restarts_as_desktop_user(elevated_portable,monkeypatch,can_close):
    import update_ui
    from updates import Release
    from unittest.mock import Mock
    manager=elevated_portable
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    monkeypatch.setattr(update_ui,'check',lambda version,installed,previews:release)
    prepare=Mock(return_value=release.version)
    restart=Mock()
    monkeypatch.setattr(update_ui,'prepare_as_desktop_user',prepare)
    monkeypatch.setattr(update_ui,'launch_as_desktop_user',restart)
    manager.check_now()
    prepare.assert_called_once_with(manager.base,release,False,manager.cancel)
    assert manager.ready_button is not None and manager.ready_prompt.isVisible()
    restart.assert_not_called()
    manager.window.confirm_discard=lambda:False
    manager.restart()
    restart.assert_not_called()
    manager.window.confirm_discard=lambda:True
    monkeypatch.setattr(manager.window,'close',lambda:can_close)
    manager.restart()
    restart.assert_called_once_with(manager.base,suspended=True)
    child=restart.return_value
    if can_close:
        child.resume.assert_called_once_with()
        child.terminate.assert_not_called()
    else:
        child.terminate.assert_called_once_with()
        child.resume.assert_not_called()
    child.close.assert_called_once_with()
    assert list(manager.base.parent.iterdir())==[manager.base]


def test_restart_without_standard_desktop_keeps_admin_window(elevated_portable,monkeypatch):
    import update_ui
    from unittest.mock import Mock
    manager=elevated_portable
    manager.user_session_update=True
    manager.window.show()
    monkeypatch.setattr(update_ui,'launch_as_desktop_user',Mock(side_effect=PermissionError))
    warning=Mock()
    monkeypatch.setattr(update_ui.QMessageBox,'warning',warning)
    manager.restart()
    warning.assert_called_once()
    assert manager.window.isVisible() and not getattr(manager.window,'_update_close_approved',False)


@pytest.mark.parametrize('relaunch_ok',[True,False],ids=['recover','report-failure'])
def test_failed_resume_cleans_up_and_retries_standard_launch(elevated_portable,monkeypatch,relaunch_ok):
    import update_ui
    from unittest.mock import Mock,call
    manager=elevated_portable
    manager.user_session_update=True
    child,replacement=Mock(),Mock()
    child.resume.side_effect=OSError('resume failed')
    launch=Mock(side_effect=[child,replacement if relaunch_ok else OSError('launch failed')])
    monkeypatch.setattr(update_ui,'launch_as_desktop_user',launch)
    warning=Mock()
    monkeypatch.setattr(update_ui.QMessageBox,'warning',warning)
    manager.window.show()
    manager.restart()
    assert launch.call_args_list==[call(manager.base,suspended=True),call(manager.base)]
    assert child.method_calls==[call.resume(),call.terminate(),call.close()]
    assert not manager.window.isVisible()
    if relaunch_ok:
        replacement.close.assert_called_once_with()
        warning.assert_not_called()
    else:
        warning.assert_called_once()
        assert warning.call_args.args[0] is None


def test_elevated_custom_machine_install_does_not_use_portable_worker(elevated_portable,monkeypatch):
    import update_ui
    from updates import Release
    from unittest.mock import Mock
    manager=elevated_portable
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    message=Mock()
    monkeypatch.setattr(update_ui,'machine_install_location',lambda base:True)
    monkeypatch.setattr(update_ui,'check',lambda *args:release)
    monkeypatch.setattr(update_ui,'prepare_as_desktop_user',lambda *args:pytest.fail('Shared installation'))
    monkeypatch.setattr(update_ui.QMessageBox,'information',message)
    manager.check_now()
    assert message.call_count==1 and release.version in message.call_args.args[-1]
    assert manager.ready_button is None and not manager.window.settings.value(manager.portable_hint_key())


@pytest.mark.parametrize('available',[True,False],ids=['still-ready','stale-hint'])
def test_elevated_portable_recovers_deferred_update(elevated_portable,monkeypatch,available):
    import update_ui
    from unittest.mock import Mock
    from updates import Release
    first=elevated_portable
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    monkeypatch.setattr(update_ui,'check',lambda *args:release)
    monkeypatch.setattr(update_ui,'prepare_as_desktop_user',lambda *args:release.version)
    first.check_now()
    settings=first.window.settings
    key=first.portable_hint_key()
    assert settings.value(key)=='2.0.13'
    settings.setValue('updates/last_check',time.time())
    first.ready_prompt.close()
    first.stop()
    manager=update_ui.UpdateManager(first.window,first.version)
    manager.base=first.base.parent/'other'/'Cadence.exe'
    assert manager.portable_hint_key()!=key
    manager.base=first.base
    probe=Mock(return_value=available)
    monkeypatch.setattr(update_ui,'prepared_as_desktop_user',probe)
    monkeypatch.setattr(update_ui,'check',lambda *args:pytest.fail('Unexpected network check on startup'))
    monkeypatch.setattr(manager,'run',lambda operation:manager.complete(operation(),''))
    try:
        manager.start()
        probe.assert_called_once_with(first.base,'2.0.13',manager.cancel)
        if available:
            assert manager.ready_button is not None and manager.ready_prompt.isVisible()
            assert '2.0.13' in manager.ready_prompt.text()
        else:
            assert manager.ready_button is None
            assert not settings.value(key)
            assert manager.seconds_until_check()==0 and manager.check_timer.isActive()
    finally:
        manager.stop()
        if manager.ready_button: manager.ready_prompt.close()


@pytest.mark.parametrize('already_downloaded',[False,True],ids=['normal-download','existing-pending'])
def test_standard_portable_download_remains_available_offline_as_admin(elevated_portable,monkeypatch,already_downloaded):
    import update_ui
    import update_user
    from update_store import STORE,write_state
    from updates import Release
    admin=elevated_portable
    base=admin.base
    settings_path=admin.window.settings.fileName()
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    store=base.parent/STORE
    def prepare(*args):
        store.mkdir(exist_ok=True)
        write_state(store,{'pending':release.version})
        return release.version
    normal=update_ui.UpdateManager(admin.window,admin.version)
    normal.base=base
    with monkeypatch.context() as standard:
        standard.setattr(update_ui,'shared_install',lambda path:False)
        standard.setattr(update_ui,'elevated_process',lambda:False)
        standard.setattr(update_ui,'check',lambda *args:release)
        standard.setattr(update_ui,'prepare_package',prepare)
        standard.setattr(normal,'run',lambda task:normal.complete(task(),''))
        if already_downloaded: prepare()
        normal.start()
        if not already_downloaded: normal.check_now()
        assert normal.ready_button is not None
        normal.ready_prompt.close()
        normal.stop()
    admin.window.settings.sync()
    admin.window.settings=QSettings(settings_path,QSettings.IniFormat)
    monkeypatch.setattr(update_ui,'check',lambda *args:pytest.fail('No network offline'))
    monkeypatch.setattr(update_user,'base_executable',lambda:base)
    monkeypatch.setattr(update_user.sys,'executable',str(base))
    monkeypatch.setattr(update_user,'shared_install',lambda path:False)
    def probe(path,version,cancel):
        assert path==base
        return update_user.prepare_requested(admin.version,['--probe-user-update',version])==0
    monkeypatch.setattr(update_ui,'prepared_as_desktop_user',probe)
    admin.start()
    assert admin.user_session_update and admin.ready_button is not None
    assert release.version in admin.ready_prompt.text()


@pytest.mark.parametrize('reply,server_matches,succeeds',[
    (b'{"state":"ready","version":"2.0.9","progress":100}\n',True,True),
    (b'{"state":"unexpected","version":"","progress":0}\n',True,False),
    (b'{"state":"ready","version":"2.0.9","progress":100}\n',False,False),
])
def test_native_pipe_validates_server_and_status(monkeypatch,reply,server_matches,succeeds):
    pipe=r'\\.\pipe\Cadence-Client-Test-'+uuid.uuid4().hex
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateNamedPipeW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,wt.DWORD,wt.DWORD,wt.DWORD,wt.DWORD,wt.LPVOID]
    api.CreateNamedPipeW.restype=wt.HANDLE
    api.ConnectNamedPipe.argtypes=[wt.HANDLE,wt.LPVOID]
    api.ReadFile.argtypes=[wt.HANDLE,wt.LPVOID,wt.DWORD,ctypes.POINTER(wt.DWORD),wt.LPVOID]
    api.WriteFile.argtypes=api.ReadFile.argtypes
    api.FlushFileBuffers.argtypes=[wt.HANDLE]
    api.CloseHandle.argtypes=[wt.HANDLE]
    handle=api.CreateNamedPipeW(pipe,3,0,1,1024,1024,1000,None)
    assert handle!=wt.HANDLE(-1).value
    seen=[]
    def serve():
        try:
            if not api.ConnectNamedPipe(handle,None) and ctypes.get_last_error()!=535: return
            buffer=ctypes.create_string_buffer(64); count=wt.DWORD()
            if not api.ReadFile(handle,buffer,64,ctypes.byref(count),None): return
            seen.append(buffer.raw[:count.value])
            api.WriteFile(handle,reply,len(reply),ctypes.byref(count),None)
            api.FlushFileBuffers(handle)
        finally: api.CloseHandle(handle)
    worker=threading.Thread(target=serve,daemon=True); worker.start()
    monkeypatch.setattr(machine,'PIPE',pipe)
    monkeypatch.setattr(machine,'service_pid',lambda:os.getpid() if server_matches else os.getpid()+1)
    if succeeds: assert machine.request('STATUS')['version']=='2.0.9'
    else:
        with pytest.raises((OSError,ValueError)): machine.request('STATUS')
    worker.join(4); assert not worker.is_alive()
    assert seen==([b'STATUS\n'] if server_matches else [])
    with pytest.raises(ValueError): machine.request('APPLY C:/file')


@pytest.mark.parametrize('elevated',[False,True],ids=['standard','administrator'])
def test_managed_user_ready_restart_and_other_sessions(gui,tmp_path,monkeypatch,elevated):
    import update_ui
    window=fake_window(gui); window.settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    manager=update_ui.UpdateManager(window,'2.0.8'); manager.base=tmp_path/'Cadence.exe'
    monkeypatch.setattr(update_ui.sys,'frozen',True,raising=False); monkeypatch.delenv('CADENCE_DISABLE_UPDATES',raising=False)
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:elevated)
    monkeypatch.setattr(machine,'configured',lambda path:True)
    monkeypatch.setattr(manager,'run',lambda operation:pytest.fail('Machine updates must use the service'))
    commands=[]; messages=[]; restarted=[]; blocked=[True]
    def send(command):
        commands.append(command)
        state={'STATUS':'trial','READY':'installed','CHECK_STABLE':'ready','APPLY':'waiting'}[command]
        return dict(state=state,version='2.0.8' if command in ('STATUS','READY') else '2.0.9',progress=100,
                    blocked=command=='APPLY' and blocked[0])
    monkeypatch.setattr(machine,'request',send)
    monkeypatch.setattr(machine.MachineUpdates,'message',lambda self,text,warning=False:messages.append(text))
    monkeypatch.setattr(manager,'restart_machine',lambda:restarted.append(True))
    def wait(pred):
        end=time.monotonic()+5
        while time.monotonic()<end and not pred(): QTest.qWait(10)
        assert pred()
    try:
        manager.start()
        wait(lambda:'READY' in commands and not manager.machine.busy)
        manager.check_now(True); wait(lambda:manager.ready_button is not None)
        assert not restarted and manager.ready_prompt.isVisible()
        manager.ready_button.click(); wait(lambda:bool(messages)); assert not restarted
        blocked[0]=False; manager.check_now(True); manager.ready_button.click()
        wait(lambda:bool(restarted))
        assert commands==['STATUS','READY','CHECK_STABLE','APPLY','APPLY']
    finally:
        manager.stop()
        if manager.ready_button: manager.ready_prompt.close()
        window.close()


@pytest.mark.parametrize('installed',[False,True],ids=['missing','unavailable'])
def test_missing_service_requests_initial_admin_setup(gui,tmp_path,monkeypatch,installed):
    import maintenance_activation as activation
    import update_ui
    window=fake_window(gui); manager=update_ui.UpdateManager(window,'2.0.8')
    manager.base=tmp_path/'Cadence.exe'; messages=[]
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:False)
    monkeypatch.setattr(machine,'configured',lambda path:False)
    monkeypatch.setattr(machine,'install_paths',lambda:(manager.base,None))
    monkeypatch.setattr(activation,'available',lambda base,version:False)
    monkeypatch.setattr(activation,'service_exists',lambda:installed)
    monkeypatch.setattr(update_ui.QMessageBox,'information',lambda parent,title,text:messages.append(text))
    monkeypatch.setattr(manager,'run',lambda task:pytest.fail('User updater must not run on protected installation'))
    manager.check_now(True)
    from ui_text import tr
    expected=(tr('Le service de maintenance est indisponible. Réessayez plus tard.') if installed else
              tr('Cette installation est protégée. Demandez à votre administrateur d’activer la maintenance dans l’installateur de Cadence.'))
    assert messages==[expected]
    manager.stop(); window.close()


@pytest.mark.parametrize('installed',[False,True],ids=['missing','unavailable'])
@pytest.mark.parametrize('new_release',[False,True],ids=['up-to-date','update-available'])
def test_elevated_install_without_service_checks_release_read_only(elevated_portable,monkeypatch,installed,new_release):
    import maintenance_activation as activation
    import update_ui
    from unittest.mock import Mock
    from updates import Release
    from ui_text import tr
    manager=elevated_portable
    monkeypatch.setattr(machine,'configured',lambda base:False)
    monkeypatch.setattr(machine,'install_paths',lambda:(manager.base,None))
    monkeypatch.setattr(activation,'available',lambda base,version:False)
    monkeypatch.setattr(activation,'service_exists',lambda:installed)
    monkeypatch.setattr(update_ui,'prepare_as_desktop_user',lambda *args:pytest.fail('Protected machine installation'))
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    check=Mock(return_value=release if new_release else None)
    message=Mock()
    monkeypatch.setattr(update_ui,'check',check)
    monkeypatch.setattr(update_ui.QMessageBox,'information',message)
    manager.start()
    assert manager.check_timer.isActive()
    manager.check_now(False)
    check.assert_called_once_with(manager.version,False,False)
    message.assert_not_called()
    manager.check_now(True)
    assert check.call_count==2 and message.call_count==1
    text=message.call_args.args[-1]
    if new_release:
        assert release.version in text and 'maintenance' in text.lower()
    else:
        assert tr('Aucune nouvelle version disponible.') in text
    assert manager.ready_button is None and not manager.user_session_update
    assert list(manager.base.parent.iterdir())==[manager.base]


@pytest.mark.parametrize('elevated',[False,True],ids=['standard','administrator'])
def test_machine_watcher_restarts_with_standard_rights(gui,tmp_path,monkeypatch,elevated):
    import update_ui
    from unittest.mock import Mock
    window=fake_window(gui)
    manager=update_ui.UpdateManager(window,'2.0.12')
    manager.base=tmp_path/'Cadence.exe'
    helper=tmp_path/'CadenceRestart.exe'
    machine_updates=machine.MachineUpdates(manager)
    monkeypatch.setattr(machine,'configured',lambda app:app==manager.base)
    monkeypatch.setattr(machine,'install_paths',lambda:(manager.base,helper))
    monkeypatch.setattr(machine,'elevated_process',lambda:elevated)
    desktop_launch,standard_launch=Mock(),Mock()
    monkeypatch.setattr(machine,'launch_as_desktop_user',desktop_launch)
    monkeypatch.setattr(machine.subprocess,'Popen',standard_launch)
    try:
        child=machine_updates.watcher()
        if elevated:
            desktop_launch.assert_called_once_with(helper)
            standard_launch.assert_not_called()
            assert child is desktop_launch.return_value
        else:
            standard_launch.assert_called_once()
            desktop_launch.assert_not_called()
            assert child is standard_launch.return_value
        monkeypatch.setattr(machine,'configured',lambda app:False)
        with pytest.raises(OSError): machine_updates.watcher()
        assert desktop_launch.call_count+standard_launch.call_count==1
    finally:
        manager.stop(); window.close()


def test_activation_rejects_user_writable_handles_and_user_build(tmp_path):
    import maintenance_activation as activation
    assert not activation.available(tmp_path/'Cadence.exe','2.0.8')
    user_file=tmp_path/'CadenceMaintenanceSetup.exe'; user_file.touch()
    with pytest.raises(PermissionError):
        with activation.protected_handle(user_file,False): pytest.fail('User file trusted')
    with activation.protected_handle(machine.install_paths()[0].parents[1],True): pass


def test_activation_requires_matching_runtime_and_absent_service(tmp_path,monkeypatch):
    import maintenance_activation as activation
    from contextlib import nullcontext
    app=tmp_path/'Cadence 2.0'/'Cadence.exe'; runtime=app.parent/'_internal-2.0.8'
    folder=runtime/'maintenance'; folder.mkdir(parents=True)
    setup=folder/'CadenceMaintenanceSetup.exe'; setup.touch(); app.touch()
    monkeypatch.setattr(activation,'install_paths',lambda:(app,None))
    monkeypatch.setattr(activation.sys,'executable',str(app)); monkeypatch.setattr(activation.sys,'frozen',True,raising=False)
    monkeypatch.setattr(activation.sys,'_MEIPASS',str(runtime),raising=False)
    monkeypatch.setattr(activation,'service_exists',lambda:False)
    checked=[]
    monkeypatch.setattr(activation,'protected_handle',lambda path,is_dir:checked.append((path,is_dir)) or nullcontext())
    assert activation.available(app,'2.0.8') and checked==[(app.parents[1],True),(app.parent,True),(runtime,True),(folder,True),(app,False),(setup,False)]
    assert not activation.available(app,'2.0.9')
    sidecar=folder/'CadenceMaintenanceSetup.exe.config'; sidecar.touch(); assert not activation.available(app,'2.0.8')
    sidecar.unlink()
    monkeypatch.setattr(activation,'service_exists',lambda:True); assert not activation.available(app,'2.0.8')


@pytest.mark.parametrize('elevated',[False,True],ids=['standard','administrator'])
def test_manual_confirmation_and_cancel_are_the_only_activation_path(gui,tmp_path,monkeypatch,elevated):
    import maintenance_activation as activation
    import update_ui
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QMessageBox
    window=fake_window(gui); window.settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    manager=update_ui.UpdateManager(window,'2.0.8'); manager.base=tmp_path/'Cadence.exe'
    calls=[]
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:elevated)
    monkeypatch.setattr(machine,'configured',lambda path:False)
    monkeypatch.setattr(machine,'install_paths',lambda:(manager.base,None))
    monkeypatch.setattr(activation,'available',lambda base,version:True)
    monkeypatch.setattr(activation,'activate',lambda base,version,hwnd:calls.append((base,version)) or False)
    from updates import Release
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    monkeypatch.setattr(update_ui,'check',lambda *args:release)
    monkeypatch.setattr(manager,'run',lambda operation:manager.complete(operation(),''))
    prompts=[]
    def click(role):
        box=QApplication.activeModalWidget()
        prompts.append(box.text())
        next(button for button in box.buttons() if box.buttonRole(button)==role).click()
    manager.check_now(False); assert not calls
    QTimer.singleShot(0,lambda:click(QMessageBox.RejectRole)); manager.check_now(True); assert not calls
    QTimer.singleShot(0,lambda:click(QMessageBox.AcceptRole)); manager.check_now(True)
    assert calls==[(manager.base,'2.0.8')] and not manager.activation_pending
    assert len(prompts)==2
    if elevated: assert all(release.version in text for text in prompts)
    manager.stop(); window.close()
