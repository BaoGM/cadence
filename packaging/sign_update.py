# SPDX-License-Identifier: GPL-3.0-only
import base64
import ctypes
import hashlib
import json
from pathlib import Path
import sys

def sign_package(package,version,preview,output):
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    from update_store import signed_message,verify_signature
    with package.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    size=package.stat().st_size
    message=signed_message(version,size,digest,preview)
    api=ctypes.WinDLL('ncrypt')
    provider,key=ctypes.c_void_p(),ctypes.c_void_p()
    def check(status):
        if status: raise OSError(f'Windows signing key unavailable (0x{status & 0xffffffff:08x})')
    check(api.NCryptOpenStorageProvider(ctypes.byref(provider),'Microsoft Software Key Storage Provider',0))
    try:
        check(api.NCryptOpenKey(provider,ctypes.byref(key),'Cadence.Windows.Update.v1',0,0))
        try:
            padding=ctypes.c_wchar_p('SHA256')
            hashed=hashlib.sha256(message.encode('ascii')).digest()
            size_out=ctypes.c_ulong()
            check(api.NCryptSignHash(key,ctypes.byref(padding),hashed,len(hashed),None,0,ctypes.byref(size_out),2))
            output_bytes=ctypes.create_string_buffer(size_out.value)
            check(api.NCryptSignHash(key,ctypes.byref(padding),hashed,len(hashed),output_bytes,len(output_bytes),ctypes.byref(size_out),2))
            signature=base64.b64encode(output_bytes.raw[:size_out.value]).decode('ascii')
        finally: api.NCryptFreeObject(key)
    finally: api.NCryptFreeObject(provider)
    verify_signature(message,signature)
    descriptor=dict(version=version,size=size,sha256=digest,preview=preview,signature=signature)
    (output/f'Cadence-{version}-update.json').write_text(json.dumps(descriptor,indent=2),encoding='ascii')
    return descriptor
