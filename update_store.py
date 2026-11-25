# SPDX-License-Identifier: GPL-3.0-only
import base64
import ctypes
import hashlib
import json
import logging
import msvcrt
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager

from updates import UpdateCancelled, version_tuple


STORE = '.cadence-updates'


def base_executable(executable=None):
    exe = Path(executable or sys.executable).resolve()
    if exe.parent.parent.name == STORE:
        return exe.parents[2] / 'Cadence.exe'
    return exe


def elevated_process():
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    security=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    security.OpenProcessToken.argtypes=(wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE))
    security.GetTokenInformation.argtypes=(wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    token=wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(),0x0008,ctypes.byref(token)):
        return True
    try:
        elevation=wintypes.DWORD()
        count=wintypes.DWORD()
        if not security.GetTokenInformation(token,20,ctypes.byref(elevation),ctypes.sizeof(elevation),ctypes.byref(count)):
            return True
        return bool(elevation.value)
    finally:
        kernel.CloseHandle(token)


def shared_install(base):
    import winreg
    from ctypes import wintypes
    if elevated_process(): return True
    base=Path(base).resolve()
    roots={os.environ.get(name) for name in ('ProgramFiles','ProgramW6432','ProgramFiles(x86)')}
    common=r'SOFTWARE\Microsoft\Windows\CurrentVersion'
    uninstall=common+r'\Uninstall\Cadence.Hybrid.Studio2_is1'
    for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,common,0,winreg.KEY_READ|view) as key:
                for name in ('ProgramFilesDir','ProgramFilesDir (x86)','ProgramW6432Dir'):
                    try: roots.add(winreg.QueryValueEx(key,name)[0])
                    except FileNotFoundError: pass
        except FileNotFoundError: pass
        except OSError: return True
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,uninstall,0,winreg.KEY_READ|view) as key:
                folder=winreg.QueryValueEx(key,'InstallLocation')[0]
                if folder and base.parent==Path(folder).resolve(): return True
        except FileNotFoundError: pass
        except OSError: return True
    if any(folder and base.is_relative_to(Path(folder).resolve()) for folder in roots): return True
    # Ask the kernel whether this token can add files and subdirectories, without writing a probe.
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    open_dir=kernel.CreateFileW
    open_dir.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE)
    open_dir.restype=wintypes.HANDLE
    handle=open_dir(str(base.parent),0x0002|0x0004,0x7,None,3,0x02000000,None)
    if handle==wintypes.HANDLE(-1).value: return True
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    kernel.CloseHandle(handle)
    return False


def prune_version(store,version):
    if not version: return
    version_tuple(version)
    path=store/version
    if path.resolve().parent!=store.resolve() or path.is_junction() or path.is_symlink(): return
    try:
        if (path/'.managed').read_text(encoding='ascii')!=version: return
        # Windows refuses deletion of a running executable. Leave that instance's resources intact.
        (path/'Cadence.exe').unlink(missing_ok=True)
        shutil.rmtree(path)
    except OSError:
        logging.info('Retained update directory %s',version)


def signed_message(version,size,digest,preview):
    version_tuple(version)
    if type(size) is not int or size<=0 or not re.fullmatch('[a-f0-9]{64}',digest) or type(preview) is not bool:
        raise ValueError('Invalid update descriptor')
    channel='preview' if preview else 'stable'
    return f'Cadence/windows-x64/v1/{channel}/{version}/{size}/{digest}'


def verify_signature(message, signature):
    blob=base64.b64decode((Path(__file__).parent/'assets/update-key.txt').read_text().strip(),validate=True)
    signature=base64.b64decode(signature,validate=True)
    api=ctypes.WinDLL('bcrypt')
    algorithm,key=ctypes.c_void_p(),ctypes.c_void_p()
    def check(status):
        if status: raise ValueError('Invalid update signature')
    check(api.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm),'RSA',None,0))
    try:
        check(api.BCryptImportKeyPair(algorithm,None,'RSAPUBLICBLOB',ctypes.byref(key),blob,len(blob),0))
        try:
            digest=hashlib.sha256(message.encode('ascii')).digest()
            padding=ctypes.c_wchar_p('SHA256')
            check(api.BCryptVerifySignature(key,ctypes.byref(padding),digest,len(digest),signature,len(signature),2))
        finally: api.BCryptDestroyKey(key)
    finally: api.BCryptCloseAlgorithmProvider(algorithm,0)


def read_state(store):
    try:
        state=json.loads((store/'state.json').read_text('utf-8'))
        if not isinstance(state,dict): raise ValueError('Invalid update state')
        for name in ('active','pending','failed','previous','installed','installing','cleanup','rollback_active'):
            if state.get(name): version_tuple(state[name])
        if 'prune' in state:
            if not isinstance(state['prune'],list) or len(state['prune'])>16: raise ValueError('Invalid cleanup state')
            for version in state['prune']: version_tuple(version)
        return state
    except FileNotFoundError: return {}


def write_state(store,state):
    temp=store/'state.tmp'
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(state,stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp,store/'state.json')


@contextmanager
def locked(store):
    with (store/'lock').open('a+b') as stream:
        stream.seek(0)
        msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        try: yield
        finally:
            stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def unpack(package,directory,cancel):
    with zipfile.ZipFile(package) as archive:
        files=archive.infolist()
        if len(files)>25000 or sum(f.file_size for f in files)>4*1024**3: raise ValueError('Oversized update')
        for item in files:
            if cancel.is_set(): raise UpdateCancelled()
            parts=item.filename.rstrip('/').split('/')
            if parts==['Cadence'] and item.is_dir(): continue
            if len(parts)<2 or parts[0]!='Cadence' or any(
                not part or part in ('.','..') or part.rstrip(' .')!=part or
                re.search(r'[\\:<>|?*"\x00-\x1f]',part) or PureWindowsPath(part).is_reserved()
                for part in parts[1:]) or stat.S_ISLNK(item.external_attr>>16):
                raise ValueError('Invalid package path')
            target=directory.joinpath(*parts[1:])
            if item.is_dir(): target.mkdir(parents=True,exist_ok=True); continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as src,target.open('xb') as dst:
                while data:=src.read(1024*1024):
                    if cancel.is_set(): raise UpdateCancelled()
                    dst.write(data)
    if not (directory/'Cadence.exe').is_file() or not ((directory/'_internal').is_dir() or
            any(path.is_dir() for path in directory.glob('_internal-[0-9]*'))):
        raise ValueError('Incomplete update')


def stage(base,release,package,digest,manifest,cancel):
    if shared_install(base): raise PermissionError('Shared installation')
    message=signed_message(release.version,release.size,digest,release.prerelease)
    verify_signature(message,manifest['signature'])
    store=base.parent/STORE
    store.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=store,prefix='download-') as temp:
        data=Path(temp)/'payload'; data.mkdir()
        with package.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=digest: raise ValueError('Changed package')
            stream.seek(0); unpack(stream,data,cancel)
        (data/'.managed').write_text(release.version,encoding='ascii')
        with locked(store):
            state=read_state(store)
            if cancel.is_set(): raise UpdateCancelled()
            if state.get('failed')==release.version: return None
            if any(version_tuple(state[k])>=version_tuple(release.version) for k in ('active','pending') if state.get(k)):
                return state.get('pending')
            target=store/release.version
            if target.exists():
                if (target/'.managed').read_text()!=release.version: raise ValueError('Unexpected version folder')
                # An interrupted stage may have renamed the completed directory before writing the pointer.
                orphan=Path(temp)/'orphan'
                target.rename(orphan)
            from update_install import runtime_name, atomic_copy
            if (data/runtime_name(release.version)).is_dir():
                atomic_copy(package,store/(release.version+'.zip'))
                descriptor=Path(temp)/'descriptor.json'
                descriptor.write_text(json.dumps(manifest),encoding='utf8')
                os.replace(descriptor,store/(release.version+'.json'))
            data.rename(target)
            state['pending']=release.version; write_state(store,state)
        return release.version


def spawn(exe,args,ready=None):
    env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1')
    env.pop('CADENCE_TRIAL_READY',None)
    if ready: env['CADENCE_TRIAL_READY']=ready.name
    return subprocess.Popen([str(exe),*args],env=env)


def startup_ready(version,executable=None):
    name=os.environ.pop('CADENCE_TRIAL_READY','')
    exe=Path(executable or sys.executable).resolve()
    if not re.fullmatch(r'ready-[0-9a-f]{32}',name): return
    if exe.parent.parent.name==STORE and exe.parent.name==version:
        (exe.parent.parent/name).touch()
    elif read_state(exe.parent/STORE).get('installing')==version:
        (exe.parent/STORE/name).touch()


def dispatch(base,version,args,*,launch=spawn,timeout=120):
    if os.environ.pop('CADENCE_KEEP_CURRENT','')=='1': return False
    store=base.parent/STORE
    if not (store/'state.json').is_file() or shared_install(base): return False
    state=read_state(store)
    if os.environ.get('CADENCE_TRIAL_READY') and state.get('installing')==version: return False
    from update_install import discard_completed, runtime_name, plain, verify_staged, digest, runtime_hashes
    plain(store)
    pending=state.get('installing') or state.get('cleanup') or state.get('pending')
    if pending and plain(plain(store/pending)/runtime_name(pending)).is_dir():
        if state.get('installing') or state.get('cleanup') or version_tuple(pending)>version_tuple(version):
            try:
                if (store/(pending+'.json')).exists() or state.get('pending')==pending and not state.get('installing'):
                    verify_staged(store,pending)
                else:
                    # Launchers through 2.0.7 did not retain the signed ZIP. Only resume a worker
                    # whose executable and runtime match the already running installed application.
                    package=store/pending
                    runtime=runtime_name(pending)
                    if pending!=version or digest(plain(package/'Cadence.exe'))!=digest(base):
                        raise ValueError('Unverified recovery executable')
                    if runtime_hashes(package/runtime)!=runtime_hashes(base.parent/runtime):
                        raise ValueError('Unverified recovery runtime')
            except (OSError,ValueError,KeyError) as error:
                logging.exception('Update package could not be authenticated')
                os.environ['CADENCE_UPDATE_ERROR']=type(error).__name__
                with locked(store):
                    state=read_state(store)
                    if state.get('pending')==pending and not state.get('installing'):
                        state.pop('pending'); state['failed']=pending; write_state(store,state)
                return False
            launch(plain(store/pending/'Cadence.exe'),['--apply-in-place',*args]); return True
    discard_completed(store,state)
    def usable(v):
        return v and version_tuple(v)>version_tuple(version) and (store/v/'Cadence.exe').is_file()
    def previously_active():
        active=state.get('active')
        if usable(active):
            try: launch(store/active/'Cadence.exe',args); return True
            except OSError: logging.exception('Could not launch previous version')
        return False
    try:
        with locked(store):
            state=read_state(store)
            pending=state.get('pending')
            if usable(pending):
                marker=store/('ready-'+uuid.uuid4().hex)
                state.pop('pending'); state['failed']=pending; write_state(store,state)
                try:
                    child=launch(store/pending/'Cadence.exe',args,marker)
                    until=time.monotonic()+timeout
                    while not marker.exists() and child.poll() is None and time.monotonic()<until:
                        time.sleep(.1)
                    if marker.exists():
                        obsolete=state.get('previous')
                        state['previous']=state.get('active')
                        state['active']=pending; state.pop('failed',None); write_state(store,state)
                        if obsolete not in (pending,state['previous']): prune_version(store,obsolete)
                        return True
                    if child.poll() is None: child.terminate(); child.wait(timeout=10)
                finally: marker.unlink(missing_ok=True)
    except OSError: logging.info('Update busy or unavailable',exc_info=True)
    return previously_active()
