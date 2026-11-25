# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
import zipfile

from update_store import STORE, locked, prune_version, read_state, spawn, version_tuple, write_state


def runtime_name(version):
    version_tuple(version)
    return '_internal-'+version


def plain(path):
    if path.is_symlink() or path.is_junction():
        raise ValueError('Unexpected link in the update layout')
    return path


def owned_path(root,name):
    relative=Path(name)
    if relative.anchor or '..' in relative.parts or not relative.parts or ':' in name:
        raise ValueError('Invalid installed path')
    first=relative.parts[0]
    if not (first in ('_internal','Licences','Associer Cadence.cmd','Cadence.exe')
            or first.startswith('_internal-') and runtime_name(first[10:])==first):
        raise ValueError('Unexpected package content')
    path=root
    for part in relative.parts:
        path=plain(path/part)
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def copy_or_link(source,target):
    try: os.link(source,target)
    except OSError: shutil.copy2(source,target)


def atomic_copy(source,target):
    temp=target.with_name('.cadence-'+uuid.uuid4().hex+'.tmp')
    try:
        copy_or_link(source,temp)
        until=time.monotonic()+15
        while True:
            try: os.replace(temp,target); return
            except PermissionError:
                if time.monotonic()>=until: raise
                time.sleep(.1)
    finally:
        temp.unlink(missing_ok=True)


def inventory(folder):
    files={}
    for path in folder.rglob('*'):
        name=path.relative_to(folder).as_posix()
        if name=='.managed': continue
        owned_path(folder,name)
        if path.is_file(): files[name]=digest(path)
    return files


def runtime_hashes(runtime):
    return {path.relative_to(runtime).as_posix():digest(path) for path in plain(runtime).rglob('*')
            if plain(path).is_file()}


def verify_staged(store,version):
    from update_store import signed_message,verify_signature
    descriptor=plain(store/(version+'.json'))
    if descriptor.stat().st_size>65536: raise ValueError('Oversized update descriptor')
    manifest=json.loads(descriptor.read_bytes())
    if manifest['version']!=version: raise ValueError('Wrong staged version')
    verify_signature(signed_message(version,manifest['size'],manifest['sha256'],manifest['preview']),manifest['signature'])
    folder=plain(store/version)
    package=plain(store/(version+'.zip'))
    files=inventory(folder)
    with package.open('rb') as stream:
        if os.fstat(stream.fileno()).st_size!=manifest['size'] or hashlib.file_digest(stream,'sha256').hexdigest()!=manifest['sha256']:
            raise ValueError('Changed signed archive')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            for entry in archive.infolist():
                if entry.is_dir(): continue
                root,separator,name=entry.filename.partition('/')
                if root!='Cadence' or not separator: raise ValueError('Unexpected archive content')
                with archive.open(entry) as src:
                    if files.pop(name,None)!=hashlib.file_digest(src,'sha256').hexdigest():
                        raise ValueError('Changed staged update')
    if files: raise ValueError('Unexpected staged file')


def installed_files(base,store):
    for manifest in (store/'installed-files.txt',base.parent/'uninstall'/'installed-files.txt'):
        plain(manifest.parent)
        if not plain(manifest).is_file(): continue
        files={}
        for line in manifest.read_text(encoding='utf-8-sig').splitlines():
            expected,divider,name=line.partition('|')
            if divider and len(expected)==64:
                try: owned_path(base.parent,name)
                except ValueError: continue
                files[Path(name).as_posix()]=expected
        return files
    return {}


def deploy_runtime(base,package,version,files):
    name=runtime_name(version)
    source=plain(package/name)
    target=plain(base.parent/name)
    if not source.is_dir(): raise ValueError('Missing versioned runtime')
    if target.exists():
        for entry,expected in files.items():
            if entry.startswith(name+'/') and digest(owned_path(base.parent,entry))!=expected:
                raise ValueError('Versioned runtime already exists with different contents')
        if {p.relative_to(base.parent).as_posix() for p in target.rglob('*') if plain(p).is_file()}!={entry for entry in files if entry.startswith(name+'/')}:
            raise ValueError('Unexpected file in versioned runtime')
        return
    with tempfile.TemporaryDirectory(dir=package.parent,prefix='prepare-') as temp:
        pending=Path(temp)/name
        shutil.copytree(source,pending,copy_function=copy_or_link)
        pending.rename(target)


def remove_runtime(base,package,version):
    runtime=runtime_name(version)
    files={path.relative_to(package).as_posix():digest(path) for path in (package/runtime).rglob('*') if plain(path).is_file()}
    for name,expected in files.items():
        path=owned_path(base.parent,name)
        if path.is_file() and digest(path)==expected:
            try: path.unlink()
            except OSError: continue
            parent=path.parent
            while parent!=base.parent:
                try: parent.rmdir()
                except OSError: break
                parent=parent.parent


def finish_files(base,package,version,files,old):
    folder=base.parent
    retained={}
    # Never remove unlisted files from portable folders or locally modified installed files.
    for name,expected in old.items():
        if name in files: continue
        if name.startswith('Licences/') or name=='Associer Cadence.cmd':
            retained[name]=expected
            continue
        path=owned_path(folder,name)
        if path.is_file() and digest(path)==expected:
            try: path.unlink()
            except PermissionError:
                retained[name]=expected
                continue
            parent=path.parent
            while parent!=folder:
                try: parent.rmdir()
                except OSError: break
                parent=parent.parent
    for name,expected in files.items():
        if name=='Cadence.exe' or name.startswith(runtime_name(version)+'/'): continue
        path=owned_path(folder,name)
        if path.exists():
            previous=digest(path)
            if previous==expected: continue
            if old.get(name)!=previous:
                copy_or_link(path,path.with_name(path.name+'.previous-'+uuid.uuid4().hex[:8]))
        path.parent.mkdir(parents=True,exist_ok=True)
        atomic_copy(package/name,path)
    contents=''.join(f'{sha}|{Path(name)}\n' for name,sha in sorted((retained|files).items()))
    manifest=package.parent/'installed-files.txt'
    temp=manifest.with_suffix('.tmp')
    temp.write_text(contents,encoding='utf-8-sig')
    os.replace(temp,manifest)
    uninstaller=plain(folder/'uninstall')
    if (uninstaller/'installed-files.txt').is_file():
        atomic_copy(manifest,plain(uninstaller/'installed-files.txt'))


def wait_ready(child,marker,timeout):
    until=time.monotonic()+timeout
    while not marker.is_file() and child.poll() is None and time.monotonic()<until: time.sleep(.05)
    if marker.is_file(): return True
    if child.poll() is None: child.terminate(); child.wait(timeout=10)
    return False


def promote(base,version,args=(),*,launch=spawn,timeout=120):
    base=plain(Path(base))
    store=plain(base.parent/STORE)
    version_tuple(version)
    package=plain(store/version)
    if plain(package/'.managed').read_text('ascii')!=version:
        raise ValueError('Unmanaged update')
    backup=plain(store/'rollback.exe')
    marker=store/('ready-'+uuid.uuid4().hex)
    until=time.monotonic()+timeout
    while True:
        guard=locked(store)
        try: guard.__enter__(); break
        except OSError:
            if time.monotonic()>=until: raise
            time.sleep(.1)
    try:
        state=read_state(store)
        if state.get('installing')==version:
            # The initial trial was interrupted. The old executable still has its matching runtime.
            atomic_copy(backup,base)
            state['active']=state.pop('rollback_active',None)
            state['failed']=version
            state.pop('installing',None); state.pop('pending',None)
            write_state(store,state)
            remove_runtime(base,package,version)
        elif version in (state.get('active'),state.get('pending')) and state.get('installed')!=version:
            files=inventory(package)
            old=installed_files(base,store)
            if not old:
                # A legacy portable has no receipt. Match only files common to both releases.
                for entry,expected in files.items():
                    if entry.startswith(runtime_name(version)+'/'):
                        name='_internal/'+entry.split('/',1)[1]
                        if owned_path(base.parent,name).is_file(): old[name]=expected
            deploy_runtime(base,package,version,files)
            atomic_copy(base,backup)
            previous=state.get('previous') if state.get('active')==version else state.get('active')
            state.update(installing=version,rollback_active=previous)
            write_state(store,state)
            success=False; replaced=False
            try:
                atomic_copy(package/'Cadence.exe',base)
                replaced=True
                success=wait_ready(launch(base,args,marker),marker,timeout)
            finally:
                if replaced and not success:
                    atomic_copy(backup,base)
                state.pop('installing',None); state.pop('rollback_active',None)
                if success:
                    state.update(installed=version,active=None,previous=None,cleanup=version)
                    state.pop('pending',None); state.pop('failed',None)
                elif replaced:
                    state.update(failed=version,active=previous)
                    state.pop('pending',None)
                else:
                    state.update(active=previous,pending=version)
                write_state(store,state)
                if replaced and not success: remove_runtime(base,package,version)
            if success:
                try: finish_files(base,package,version,files,old)
                except OSError:
                    logging.exception('Deferred cleanup of installed update files')
                    return True
                state.pop('cleanup',None)
                state['prune']=[v for v in (previous,version) if v]
                write_state(store,state)
                return True
        elif state.get('installed')==version and state.get('cleanup')==version:
            files=inventory(package)
            finish_files(base,package,version,files,installed_files(base,store))
            state.pop('cleanup',None); state['prune']=[version]; write_state(store,state)
    finally:
        marker.unlink(missing_ok=True)
        guard.__exit__(None,None,None)
    launch(base,args)
    return False


def discard_completed(store,state):
    if not state.get('prune'): return
    with locked(store):
        state=read_state(store)
        deferred=[]
        for version in state.pop('prune',[]):
            if version not in (state.get('active'),state.get('pending'),state.get('installing')):
                prune_version(store,version)
                if (store/version/'.managed').is_file(): deferred.append(version)
                else:
                    (store/(version+'.json')).unlink(missing_ok=True)
                    (store/(version+'.zip')).unlink(missing_ok=True)
        if deferred: state['prune']=deferred
        (store/'rollback.exe').unlink(missing_ok=True)
        write_state(store,state)


def run_worker(base,version,args):
    try:
        def launch(exe,arguments,ready=None):
            if not ready and read_state(base.parent/STORE).get('failed')==version:
                os.environ['CADENCE_UPDATE_ERROR']='Rollback'
            return spawn(exe,arguments,ready)
        promote(base,version,args,launch=launch)
    except (OSError,ValueError) as error:
        logging.exception('In-place update failed')
        # The installed executable always has its matching runtime, including after a power loss.
        os.environ['CADENCE_KEEP_CURRENT']='1'
        os.environ['CADENCE_UPDATE_ERROR']=type(error).__name__
        spawn(base,args)
