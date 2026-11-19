# SPDX-License-Identifier: GPL-3.0-only
import copy
import json
import os
from pathlib import Path
import uuid

from preferences import preference_path


VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.mpg', '.mpeg', '.mts', '.m2ts', '.wmv', '.gif'}


def canonical(path):
    return str(Path(path).expanduser().resolve())


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def unique_paths(paths):
    result, seen = [], set()
    for value in paths:
        path = canonical(value); key = path_key(path)
        if key not in seen:
            seen.add(key); result.append(path)
    return result


def scan_folder(path):
    directories, files = [], []
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False): directories.append(canonical(entry.path))
            elif entry.is_file() and Path(entry.name).suffix.lower() in VIDEO_EXTENSIONS: files.append(canonical(entry.path))
    return sorted(directories, key=str.casefold), sorted(files, key=str.casefold)


def has_subfolders(path):
    try:
        with os.scandir(path) as entries:
            return any(entry.is_dir(follow_symlinks=False) for entry in entries)
    except OSError:
        return False


class PlaylistStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else preference_path().with_name('playlists.json')
        self.entries = []
        if self.path.exists():
            if self.path.stat().st_size > 16 * 1024 * 1024: raise ValueError('Bibliothèque de listes trop volumineuse.')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('format') != 'cadence-playlists' or data.get('version') != 1:
                raise ValueError('Bibliothèque de listes incompatible.')
            entries = data.get('entries')
            if not isinstance(entries, list) or len(entries) > 10000: raise ValueError('Bibliothèque de listes invalide.')
            ids = set()
            for item in entries:
                if not isinstance(item, dict) or item.get('kind') not in ('folder', 'list'):
                    raise ValueError('Liste de lecture invalide.')
                if any(not isinstance(item.get(k), str) or not item[k] for k in ('id', 'name')) or item['id'] in ids:
                    raise ValueError('Liste de lecture invalide.')
                ids.add(item['id'])
                if item['kind'] == 'list': self.validate_paths(item.get('files'))
                else:
                    if not isinstance(item.get('root'), str) or not isinstance(item.get('folders'), dict):
                        raise ValueError('Dossier suivi invalide.')
                    for folder, record in item['folders'].items():
                        if not Path(folder).is_absolute() or not isinstance(record, dict): raise ValueError('Dossier suivi invalide.')
                        self.validate_paths(record.get('files')); self.validate_paths(record.get('excluded'))
            self.entries = entries

    @staticmethod
    def validate_paths(values):
        if not isinstance(values, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in values):
            raise ValueError('Chemins de vidéos invalides.')

    def commit(self, entries):
        text = json.dumps(dict(format='cadence-playlists', version=1, entries=entries), ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(text, encoding='utf-8'); temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.entries = entries

    def entry(self, identity):
        return next(item for item in self.entries if item['id'] == identity)

    def create(self, name, paths=(), root=None):
        entry = dict(id=uuid.uuid4().hex, name=name.strip() or 'Liste', kind='folder' if root else 'list')
        if root: entry.update(root=canonical(root), folders={})
        else: entry['files'] = unique_paths(paths)
        self.commit(self.entries + [entry])
        return entry['id']

    def update(self, identity, operation):
        entries = copy.deepcopy(self.entries)
        item = next(item for item in entries if item['id'] == identity)
        operation(item); self.commit(entries)

    def folder_name(self, identity, folder):
        item = self.entry(identity)
        if path_key(folder) == path_key(item['root']): return item['name']
        return item.get('folder_names', {}).get(canonical(folder), Path(folder).name)

    def rename(self, identity, name, folder=None):
        if not name.strip(): return
        def operation(item):
            if folder and path_key(folder) != path_key(item['root']):
                item.setdefault('folder_names', {})[canonical(folder)] = name.strip()
            else: item['name'] = name.strip()
        self.update(identity, operation)

    def remove(self, identity):
        self.commit([item for item in self.entries if item['id'] != identity])

    def files(self, identity, folder=None):
        item = self.entry(identity)
        if item['kind'] == 'list': return list(item['files'])
        return list(item['folders'].get(canonical(folder or item['root']), {}).get('files', []))

    def scanned(self, identity, folder, files, refresh=False):
        folder = canonical(folder)
        def operation(item):
            previous = item['folders'].get(folder, dict(files=[], excluded=[]))
            excluded = [] if refresh else previous['excluded']
            excluded_keys = {path_key(p) for p in excluded}
            available = {path_key(p): p for p in files if path_key(p) not in excluded_keys}
            ordered = [available.pop(path_key(p)) for p in previous['files'] if path_key(p) in available]
            item['folders'][folder] = dict(files=ordered + list(available.values()), excluded=excluded)
        self.update(identity, operation)

    def set_files(self, identity, paths, folder=None, removed=()):
        paths = unique_paths(paths)
        def operation(item):
            if item['kind'] == 'list': item['files'] = paths
            else:
                record = item['folders'].setdefault(canonical(folder or item['root']), dict(files=[], excluded=[]))
                record['files'] = paths
                keys = {path_key(p) for p in paths}
                record['excluded'] = [p for p in unique_paths(record['excluded'] + list(removed))
                                      if path_key(p) not in keys]
        self.update(identity, operation)


def copy_into_folder(paths, folder, progress, cancel):
    from media import Cancelled
    root = Path(folder); copied, result = [], []
    try:
        for index, value in enumerate(paths):
            source = Path(value)
            if cancel.is_set(): raise Cancelled()
            if path_key(source.parent) == path_key(root):
                result.append(canonical(source)); continue
            suffix = 1
            while True:
                target = root / (source.name if suffix == 1 else f'{source.stem} ({suffix}){source.suffix}')
                try: output = target.open('xb'); break
                except FileExistsError: suffix += 1
            copied.append(target)
            total, done = max(1, source.stat().st_size), 0
            with output, source.open('rb') as input_file:
                while block := input_file.read(4 * 1024 * 1024):
                    if cancel.is_set(): raise Cancelled()
                    output.write(block); done += len(block)
                    progress((index + done / total) / len(paths), 'Copie des vidéos')
            result.append(canonical(target))
        return result
    except BaseException:
        for target in copied: target.unlink(missing_ok=True)
        raise
