# SPDX-License-Identifier: GPL-3.0-only
import hashlib
from pathlib import Path
from threading import Event
import zipfile

import pytest

from updates import Release
from update_install import promote, verify_staged
from update_store import STORE, dispatch, read_state, stage, write_state


@pytest.fixture
def installation(tmp_path,monkeypatch):
    root=tmp_path/'Cadence portable'; root.mkdir()
    base=root/'Cadence.exe'; base.write_bytes(b'old application')
    old=root/'_internal'; old.mkdir()
    (old/'cadence.dll').write_bytes(b'old library')
    (old/'my-notes.txt').write_bytes(b'user')
    (root/'user.cadence').write_bytes(b'edit')
    uninstall=root/'uninstall'; uninstall.mkdir()
    (uninstall/'installed-files.txt').write_text(hashlib.sha256(b'old library').hexdigest()+'|_internal\\cadence.dll\n')
    version='2.0.8'
    pkg=tmp_path/'release.zip'
    with zipfile.ZipFile(pkg,'w') as archive:
        for path,content in {'Cadence.exe':b'new application','_internal-2.0.8/cadence.dll':b'new library',
                '_internal/layout.txt':b'_internal-2.0.8','Licences/COPYING.txt':b'GPLv3'}.items():
            archive.writestr('Cadence/'+path,content)
    digest=hashlib.sha256(pkg.read_bytes()).hexdigest()
    release=Release(version,True,pkg.name,pkg.stat().st_size,digest)
    manifest=dict(version=version,preview=True,size=release.size,sha256=digest,signature='fixture')
    monkeypatch.setattr('update_store.verify_signature',lambda msg,sig:None)
    assert stage(base,release,pkg,digest,manifest,Event())==version
    return base,version


@pytest.mark.parametrize('healthy',[False,True])
def test_restart_replaces_original_executable_or_rolls_back(installation,healthy):
    base,version=installation; folder=base.parent; store=folder/STORE
    assert base.read_bytes()==b'old application' and not (folder/'_internal-2.0.8').exists()
    calls=[]
    assert dispatch(base,'2.0.7',['example.mov'],launch=lambda exe,args:calls.append((exe,args)))
    assert calls==[(store/version/'Cadence.exe',['--apply-in-place','example.mov'])]
    class Child:
        def poll(self): return 0 if healthy else 1
    def start(executable,args,ready=None):
        calls.append((executable,list(args)))
        assert executable==base
        if ready:
            assert executable.read_bytes()==b'new application'
            assert (folder/'_internal-2.0.8'/'cadence.dll').read_bytes()==b'new library'
            if healthy: ready.touch()
        return Child()
    assert promote(base,version,['example.mov'],launch=start)==healthy
    assert base.read_bytes()==(b'new application' if healthy else b'old application')
    assert (folder/'_internal'/'cadence.dll').exists()!=healthy
    assert (folder/'_internal'/'my-notes.txt').read_bytes()==b'user'
    assert (folder/'_internal-2.0.8').exists()==healthy
    assert (folder/'user.cadence').read_bytes()==b'edit'
    state=read_state(store)
    assert 'installing' not in state and 'pending' not in state
    assert state['installed' if healthy else 'failed']==version
    assert calls[-1]==(base,['example.mov'])


def test_interrupted_trial_restores_base_and_arguments(installation):
    base,version=installation; store=base.parent/STORE
    backup=store/'rollback.exe'; backup.write_bytes(base.read_bytes())
    base.write_bytes(b'new application')
    write_state(store,dict(installing=version,pending=version))
    calls=[]
    assert not promote(base,version,['saved.cadence'],launch=lambda exe,args:calls.append((exe,args)))
    assert base.read_bytes()==b'old application' and calls==[(base,['saved.cadence'])]
    assert read_state(store)['failed']==version


def test_tampered_staging_refuses_to_start(installation,monkeypatch):
    base,version=installation; store=base.parent/STORE
    monkeypatch.setenv('CADENCE_UPDATE_ERROR','')
    verify_staged(store,version)
    (store/version/'_internal-2.0.8'/'cadence.dll').write_bytes(b'changed')
    with pytest.raises(ValueError): verify_staged(store,version)
    assert not dispatch(base,'2.0.7',[],launch=lambda *args:pytest.fail('untrusted launch'))
    assert base.read_bytes()==b'old application'


def test_in_use_installation_retries_on_next_restart(installation,monkeypatch):
    import update_install
    base,version=installation; store=base.parent/STORE
    copy=update_install.atomic_copy
    def locked(source,target):
        if target==base: raise PermissionError('application is in use')
        return copy(source,target)
    monkeypatch.setattr(update_install,'atomic_copy',locked)
    with pytest.raises(PermissionError): promote(base,version,launch=lambda *args:pytest.fail('unexpected restart'))
    state=read_state(store)
    assert state.get('pending')==version and not state.get('failed') and not state.get('installing')
    assert base.read_bytes()==b'old application'
