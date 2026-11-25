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


def test_managed_user_ready_restart_and_other_sessions(gui,tmp_path,monkeypatch):
    import update_ui
    window=fake_window(gui); window.settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    manager=update_ui.UpdateManager(window,'2.0.8'); manager.base=tmp_path/'Cadence.exe'
    monkeypatch.setattr(update_ui.sys,'frozen',True,raising=False); monkeypatch.delenv('CADENCE_DISABLE_UPDATES',raising=False)
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:False)
    monkeypatch.setattr(machine,'configured',lambda path:True)
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


def test_missing_service_requests_initial_admin_setup(gui,tmp_path,monkeypatch):
    import update_ui
    window=fake_window(gui); manager=update_ui.UpdateManager(window,'2.0.8')
    manager.base=tmp_path/'Cadence.exe'; messages=[]
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:False)
    monkeypatch.setattr(machine,'configured',lambda path:False)
    monkeypatch.setattr(machine,'install_paths',lambda:(manager.base,None))
    monkeypatch.setattr(update_ui.QMessageBox,'information',lambda parent,title,text:messages.append(text))
    monkeypatch.setattr(manager,'run',lambda task:pytest.fail('User updater must not run on protected installation'))
    manager.check_now(True)
    assert len(messages)==1 and 'maintenance' in messages[0].lower()
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
    monkeypatch.setattr(activation,'elevated_process',lambda:False)
    monkeypatch.setattr(activation,'service_exists',lambda:False)
    checked=[]
    monkeypatch.setattr(activation,'protected_handle',lambda path,is_dir:checked.append((path,is_dir)) or nullcontext())
    assert activation.available(app,'2.0.8') and checked==[(app.parents[1],True),(app.parent,True),(runtime,True),(folder,True),(app,False),(setup,False)]
    assert not activation.available(app,'2.0.9')
    sidecar=folder/'CadenceMaintenanceSetup.exe.config'; sidecar.touch(); assert not activation.available(app,'2.0.8')
    sidecar.unlink()
    monkeypatch.setattr(activation,'service_exists',lambda:True); assert not activation.available(app,'2.0.8')


def test_manual_confirmation_and_cancel_are_the_only_activation_path(gui,tmp_path,monkeypatch):
    import maintenance_activation as activation
    import update_ui
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QMessageBox
    window=fake_window(gui); window.settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    manager=update_ui.UpdateManager(window,'2.0.8'); manager.base=tmp_path/'Cadence.exe'
    calls=[]
    monkeypatch.setattr(update_ui,'shared_install',lambda base:True)
    monkeypatch.setattr(update_ui,'elevated_process',lambda:False)
    monkeypatch.setattr(machine,'configured',lambda path:False)
    monkeypatch.setattr(machine,'install_paths',lambda:(manager.base,None))
    monkeypatch.setattr(activation,'available',lambda base,version:True)
    monkeypatch.setattr(activation,'activate',lambda base,version,hwnd:calls.append((base,version)) or False)
    def click(role):
        box=QApplication.activeModalWidget()
        next(button for button in box.buttons() if box.buttonRole(button)==role).click()
    manager.check_now(False); assert not calls
    QTimer.singleShot(0,lambda:click(QMessageBox.RejectRole)); manager.check_now(True); assert not calls
    QTimer.singleShot(0,lambda:click(QMessageBox.AcceptRole)); manager.check_now(True)
    assert calls==[(manager.base,'2.0.8')] and not manager.activation_pending
    manager.stop(); window.close()
