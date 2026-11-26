# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path

import pytest


pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows installation scope')


def test_program_files_uses_machine_locations_not_only_environment(monkeypatch):
    import winreg
    from update_store import shared_install
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion',0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        protected=Path(winreg.QueryValueEx(key,'ProgramFilesDir')[0])
    for name in ('ProgramFiles','ProgramW6432','ProgramFiles(x86)'):
        monkeypatch.delenv(name,raising=False)
    assert shared_install(protected/'Cadence.exe')


def test_custom_all_users_install_in_alternate_registry_view(tmp_path,monkeypatch):
    import winreg
    from update_store import shared_install
    from contextlib import nullcontext
    key_path=r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Cadence.Hybrid.Studio2_is1'
    visited=[]
    def open_key(hive,path,unused,access):
        visited.append((path,access))
        if path==key_path and access & winreg.KEY_WOW64_32KEY:
            return nullcontext(object())
        raise FileNotFoundError
    monkeypatch.setattr(winreg,'OpenKey',open_key)
    monkeypatch.setattr(winreg,'QueryValueEx',lambda key,name:(str(tmp_path),winreg.REG_SZ))
    assert shared_install(tmp_path/'Cadence.exe')
    assert (key_path,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) in visited


def test_elevated_client_never_stages_or_launches_user_updates(tmp_path,monkeypatch):
    from threading import Event
    from update_store import STORE,dispatch,shared_install,stage,write_state
    from updates import Release
    app=tmp_path/'Cadence.exe'
    store=tmp_path/STORE
    monkeypatch.setattr('update_store.elevated_process',lambda:True)
    assert shared_install(app)
    release=Release('2.0.13',False,'unused.zip',1,None)
    with pytest.raises(PermissionError):
        stage(app,release,tmp_path/'unused.zip','',{},Event())
    assert not store.exists()
    store.mkdir()
    write_state(store,{'pending':release.version})
    assert not dispatch(app,'2.0.12',[],launch=lambda *args:pytest.fail('Elevated launch'))


@pytest.mark.parametrize('opened',[False,True],ids=['open-token-fails','query-token-fails'])
def test_unreadable_token_is_treated_as_protected(tmp_path,monkeypatch,opened):
    import ctypes
    from unittest.mock import Mock
    from update_store import elevated_process,shared_install
    kernel,security=Mock(),Mock()
    security.OpenProcessToken.return_value=int(opened)
    security.GetTokenInformation.return_value=0
    libraries={'kernel32':kernel,'advapi32':security}
    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kwargs:libraries[name])
    assert elevated_process()
    assert shared_install(tmp_path/'Cadence.exe')
    assert kernel.CloseHandle.call_count==(2 if opened else 0)


def test_user_update_folder_check_creates_no_files(tmp_path,monkeypatch):
    from update_store import shared_install
    monkeypatch.setattr('update_store.elevated_process',lambda:False)
    assert not shared_install(tmp_path/'Cadence.exe')
    assert shared_install(tmp_path/'not-present'/'Cadence.exe')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(('shared','found','status'),[
    (True,'2.0.13',5),
    (False,'2.0.14',2),
    (False,'2.0.13',0),
],ids=['protected-scope','release-changed','portable'])
def test_background_worker_rechecks_release_and_scope(tmp_path,monkeypatch,shared,found,status):
    from unittest.mock import Mock
    from updates import Release
    import update_user
    base=tmp_path/'Cadence.exe'
    release=Release(found,False,'unused.zip',1,'0'*64)
    monkeypatch.setattr(update_user,'base_executable',lambda:base)
    monkeypatch.setattr(update_user.sys,'executable',str(base))
    monkeypatch.setattr(update_user.sys,'frozen',True,raising=False)
    monkeypatch.setattr(update_user,'shared_install',lambda path:shared)
    check=Mock(return_value=release)
    prepare=Mock(return_value=found)
    monkeypatch.setattr(update_user,'check',check)
    monkeypatch.setattr(update_user,'prepare_package',prepare)
    assert update_user.prepare_requested('2.0.12',['--prepare-user-update','preview','2.0.13'])==status
    if shared: check.assert_not_called()
    else: check.assert_called_once_with('2.0.12',False,True)
    if status==0:
        assert prepare.call_count==1 and prepare.call_args.args[:2]==(base,release)
    else:
        prepare.assert_not_called()


@pytest.mark.parametrize('status,expected',[(0,'2.0.13'),(2,None),(5,PermissionError),(1,OSError)])
def test_background_worker_result_controls_ready_prompt(tmp_path,monkeypatch,status,expected):
    from threading import Event
    from unittest.mock import Mock
    from updates import Release
    import update_user
    app=tmp_path/'Cadence.exe'
    release=Release('2.0.13',False,'unused.zip',1,'0'*64)
    child=Mock()
    child.wait.return_value=status
    launch=Mock(return_value=child)
    monkeypatch.setattr(update_user,'launch_as_desktop_user',launch)
    if isinstance(expected,type):
        with pytest.raises(expected):
            update_user.prepare_as_desktop_user(app,release,False,Event())
    else:
        assert update_user.prepare_as_desktop_user(app,release,False,Event())==expected
    launch.assert_called_once_with(app,['--prepare-user-update','stable','2.0.13'])
    child.close.assert_called_once_with()


@pytest.fixture
def desktop_apis(tmp_path,monkeypatch):
    import ctypes
    from unittest.mock import Mock
    import update_desktop
    app=tmp_path/'Cadence.exe'
    kernel,user,security,profiles=Mock(),Mock(),Mock(),Mock()
    user.GetShellWindow.return_value=1
    user.GetWindowThreadProcessId.return_value=1
    kernel.OpenProcess.return_value=12
    monkeypatch.setattr(update_desktop,'base_executable',lambda:app)
    monkeypatch.setattr(update_desktop,'install_paths',lambda:(app,None))
    dlls={'kernel32':kernel,'user32':user,'advapi32':security,'userenv':profiles}
    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kwargs:dlls[name])
    monkeypatch.setattr(update_desktop._winapi,'CloseHandle',Mock())
    return app,kernel,user,security,profiles


@pytest.mark.parametrize('failure',['desktop','open-token','query-token'])
def test_missing_desktop_or_unreadable_desktop_token_never_launches(desktop_apis,failure):
    import update_desktop
    app,kernel,user,security,profiles=desktop_apis
    user.GetShellWindow.return_value=0 if failure=='desktop' else 1
    security.OpenProcessToken.return_value=int(failure!='open-token')
    security.GetTokenInformation.return_value=0
    with pytest.raises(OSError):
        update_desktop.launch_as_desktop_user(app)
    profiles.CreateEnvironmentBlock.assert_not_called()
    kernel.CreateProcessW.assert_not_called()


@pytest.mark.parametrize('identity',['matches','other-user','other-session','elevated'])
def test_child_identity_checked_before_resume(desktop_apis,monkeypatch,identity):
    import ctypes
    from ctypes import wintypes as wt
    from unittest.mock import Mock,call
    import update_desktop
    app,kernel,_,security,profiles=desktop_apis
    shell,child_process,desktop_env=12,13,1234
    def open_token(process,access,result):
        ctypes.cast(result,ctypes.POINTER(wt.HANDLE))[0]=process+100
        return True
    def token_info(token,kind,buffer,size,written):
        child=token.value==child_process+100
        if kind in (1,25):
            ctypes.cast(buffer,ctypes.POINTER(wt.LPVOID))[0]=token.value
        elif kind==12:
            ctypes.cast(buffer,ctypes.POINTER(wt.DWORD))[0]=2 if child and identity=='other-session' else 1
        elif kind==20 and child and identity=='elevated':
            ctypes.cast(buffer,ctypes.POINTER(wt.DWORD))[0]=1
        return True
    def environment(result,token,inherit):
        assert token.value==shell+100 and not inherit
        ctypes.cast(result,ctypes.POINTER(wt.LPVOID))[0]=desktop_env
        return True
    def attribute_list(buffer,count,flags,size):
        ctypes.cast(size,ctypes.POINTER(ctypes.c_size_t))[0]=64
        return buffer is not None
    def create_process(executable,command,psa,tsa,inherit,flags,env,cwd,startup,result):
        assert executable==str(app) and not inherit
        assert flags & 4 and env.value==desktop_env
        info=ctypes.cast(result,ctypes.POINTER(update_desktop.ProcessInfo)).contents
        info.process,info.thread=child_process,14
        return True
    security.OpenProcessToken.side_effect=open_token
    security.GetTokenInformation.side_effect=token_info
    security.GetSidSubAuthority.return_value=ctypes.pointer(wt.DWORD(0x2000))
    security.EqualSid.return_value=identity!='other-user'
    profiles.CreateEnvironmentBlock.side_effect=environment
    kernel.InitializeProcThreadAttributeList.side_effect=attribute_list
    kernel.CreateProcessW.side_effect=create_process
    child=Mock()
    monkeypatch.setattr(update_desktop,'DesktopProcess',lambda process,thread:child)
    if identity=='matches':
        assert update_desktop.launch_as_desktop_user(app) is child
        assert child.method_calls==[call.resume()]
    else:
        with pytest.raises(PermissionError):
            update_desktop.launch_as_desktop_user(app)
        assert child.method_calls==[call.terminate(),call.close()]
    kernel.CreateProcessW.assert_called_once()
    profiles.DestroyEnvironmentBlock.assert_called_once()
