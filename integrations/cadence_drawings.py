# SPDX-License-Identifier: GPL-3.0-only
import os
import sys
import zipfile

if __package__:
    from .cadence_runtime import finite, fs_path, fullmatch, hash_file, integer_types, load_source, read_json, real_path, string_types
else:
    from cadence_runtime import finite, fs_path, fullmatch, hash_file, integer_types, load_source, read_json, real_path, string_types


def module(host):
    if host not in ('blender', 'maya'):
        raise ValueError('Unsupported host')
    name = 'cadence_drawings_' + host
    return load_source((__package__+'.' if __package__ else '')+name, os.path.join(os.path.dirname(fs_path(__file__)), name + '.py'))


def integer(value):
    return not isinstance(value, bool) and isinstance(value, integer_types)


def number(value):
    return not isinstance(value, bool) and isinstance(value, integer_types + (float,)) and finite(value)


def checked_file(folder, name, limit):
    path = real_path(os.path.join(folder, name))
    if os.path.normcase(os.path.dirname(path)) != os.path.normcase(folder) or not os.path.isfile(path) or os.path.getsize(path) > limit:
        raise ValueError('Invalid drawing file path or size')
    return path


def load_bundle(path, root):
    if not os.path.isdir(fs_path(root)):
        raise ValueError('Drawing transfer path outside the allowed folder')
    path, root = real_path(path), real_path(root)
    if not os.path.normcase(path).startswith(os.path.normcase(root).rstrip(os.sep) + os.sep) or os.path.basename(path) != 'manifest.json':
        raise ValueError('Drawing transfer path outside the allowed folder')
    if os.path.getsize(path) > 64 * 1024 * 1024:
        raise ValueError('Drawing transfer too large')
    folder = os.path.dirname(path)
    data = read_json(path)
    if not isinstance(data, dict) or data.get('version') != 1 or data.get('mode') not in ('native', 'images', 'blue_pencil', 'grease_pencil'):
        raise ValueError('Unsupported drawing transfer')
    for name in ('owner', 'revision'):
        if not fullmatch('[0-9a-f]{32}', data.get(name, '')):
            raise ValueError('Invalid drawing identifier')
    if not isinstance(data.get('camera'), string_types) or len(data['camera']) > 1024:
        raise ValueError('Invalid camera')
    for dimension in ('width', 'height'):
        if not integer(data.get(dimension)) or not 2 <= data[dimension] <= 4096:
            raise ValueError('Invalid image size')
    keys = data.get('keys')
    if not isinstance(keys, list) or len(keys) > 10000:
        raise ValueError('Invalid drawing keys')
    for key in keys:
        if not isinstance(key, dict) or any(not integer(key.get(n)) for n in ('start', 'end')) or not -1000000 <= key['start'] < key['end'] <= 1000000:
            raise ValueError('Invalid drawing range')
        if not fullmatch(r'\d{6}\.png', key.get('image', '')):
            raise ValueError('Invalid drawing image')
        image = checked_file(folder, key['image'], 128 * 1024 * 1024)
        if hash_file(image) != key['sha256']:
            raise ValueError('Drawing image checksum mismatch')
        for frame, alpha in key['envelope']:
            if not integer(frame) or not -1001000 <= frame <= 1001000 or not number(alpha) or not 0 <= alpha <= 1:
                raise ValueError('Invalid drawing opacity')
        for stroke in key.get('strokes') or []:
            if len(stroke['points']) > 1000000 or len(stroke['color']) != 4:
                raise ValueError('Invalid stroke')
            for point in stroke['points']:
                if len(point) != 3 or any(not number(v) or abs(v) > 1000 for v in point):
                    raise ValueError('Invalid stroke point')
            if any(not number(v) or not 0 <= v <= 1 for v in stroke['color']):
                raise ValueError('Invalid stroke color')
    sequence = data.get('sequence', [])
    if not isinstance(sequence, list) or len(sequence) > 25000:
        raise ValueError('Invalid drawing sequence')
    previous, total = -1001001, 0
    for item in sequence:
        frame = item.get('frame')
        if not integer(frame) or not previous < frame <= 1001000:
            raise ValueError('Invalid sequence frame')
        previous = frame
        if not fullmatch(r'composite\.\d{6}\.png', item.get('image', '')):
            raise ValueError('Invalid sequence image')
        image = checked_file(folder, item['image'], 128 * 1024 * 1024)
        total += os.path.getsize(image)
        if total > 2 * 1024**3:
            raise ValueError('Drawing sequence too large')
        if hash_file(image) != item.get('sha256'):
            raise ValueError('Drawing image checksum mismatch')
    if data['mode'] == 'blue_pencil':
        if data.get('archive') != 'blue-pencil.zip' or not fullmatch(r'Cadence_[0-9a-f]{32}_[0-9a-f]{8}', data.get('layer_name', '')):
            raise ValueError('Invalid Blue Pencil archive')
        archive = checked_file(folder, data['archive'], 2 * 1024**3)
        if hash_file(archive) != data['archive_sha256']:
            raise ValueError('Blue Pencil archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            if len(z.infolist()) > 25001 or sum(i.file_size for i in z.infolist()) > 2 * 1024**3 or any(not fullmatch(r'drawings/(drawings.xml|frame_[+-]\d+\.png)', i.filename) for i in z.infolist()):
                raise ValueError('Invalid Blue Pencil archive entries')
    if sys.version_info[0] >= 3:
        from pathlib import Path
        folder = Path(folder)
    return data, folder


def execute(host, message, root):
    target = module(host)
    if message['type'] == 'drawing_cameras':
        return dict(type='drawing_cameras', cameras=target.cameras())
    if message['type'] == 'drawing_remove':
        if message.get('scope') != 'all_cadence':
            raise ValueError('Invalid drawing removal scope')
        target.clear()
        return dict(type='drawing_result', request=message['request'], ok=True, removed=True)
    data, folder = load_bundle(message['path'], root)
    result = target.apply(data, folder)
    return dict(type='drawing_result', request=message['request'], ok=True, **result)


def execute_steps(host,message,root):
    if host!='maya' or message['type']!='drawing_send':
        yield dict(result=execute(host,message,root)); return
    target=module(host)
    data,folder=load_bundle(message['path'],root)
    for update in target.apply_steps(data,folder):
        if 'result' in update:
            yield dict(result=dict(type='drawing_result',request=message['request'],ok=True,**update['result']))
        else: yield update
