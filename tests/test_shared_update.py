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
    from update_store import shared_install
    monkeypatch.setattr('update_store.elevated_process',lambda:True)
    assert shared_install(tmp_path/'Cadence.exe')


def test_user_update_folder_check_creates_no_files(tmp_path,monkeypatch):
    from update_store import shared_install
    monkeypatch.setattr('update_store.elevated_process',lambda:False)
    assert not shared_install(tmp_path/'Cadence.exe')
    assert shared_install(tmp_path/'not-present'/'Cadence.exe')
    assert not list(tmp_path.iterdir())
