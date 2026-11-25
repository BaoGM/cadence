# SPDX-License-Identifier: GPL-3.0-only
import json
import os
import tempfile
from pathlib import Path


PROJECT_BYTES = 64 * 1024 * 1024


class ProjectSizeError(ValueError):
    pass


def read_json(path, size_limit, error):
    with Path(path).open('rb') as stream:
        file_size = os.fstat(stream.fileno()).st_size
        if file_size > size_limit:
            raise ValueError(error)
        data = stream.read(file_size + 1)
        if len(data) > file_size:
            raise ValueError(error)
    return json.loads(data.decode('utf-8'))


def write_project(path, data):
    chunks = json.JSONEncoder(ensure_ascii=False, separators=(',', ':')).iterencode(data)
    write_json_chunks(path, chunks, PROJECT_BYTES, 'Fichier de projet trop volumineux.')


def write_json_chunks(path, chunks, size_limit, error):
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            size = 0
            for chunk in chunks:
                if len(chunk) > size_limit - size:
                    raise ProjectSizeError(error)
                for start in range(0, len(chunk), 262144):
                    encoded = chunk[start:start + 262144].encode('utf-8')
                    size += len(encoded)
                    if size > size_limit:
                        raise ProjectSizeError(error)
                    stream.write(encoded)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
