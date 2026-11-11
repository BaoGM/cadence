# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_inputs
import fetch_release_inputs
import release


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize('name', ['../outside.txt', 'C:/outside.txt', '/outside.txt', 'file:stream', 'dir\\file'])
def test_source_manifest_rejects_unsafe_paths(tmp_path, monkeypatch, name):
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/source-files.txt').write_text(name, encoding='utf-8')
    monkeypatch.setattr(build_inputs, 'SOURCE', tmp_path)
    with pytest.raises(ValueError, match='Unsafe'):
        build_inputs.source_files()


def test_dependency_manifest_rejects_changed_and_extra_files(tmp_path):
    (tmp_path / 'a.txt').write_bytes(b'original')
    expected = {'a.txt': digest(b'original')}
    assert build_inputs.verify_tree(tmp_path, expected) == expected
    (tmp_path / 'a.txt').write_bytes(b'changed')
    with pytest.raises(ValueError, match='mismatch'):
        build_inputs.verify_tree(tmp_path, expected)
    (tmp_path / 'a.txt').write_bytes(b'original')
    (tmp_path / 'unexpected.txt').write_bytes(b'extra')
    with pytest.raises(ValueError, match='mismatch'):
        build_inputs.verify_tree(tmp_path, expected)


@pytest.mark.parametrize('name', ['../outside.txt', 'C:/outside.txt', '/outside.txt', 'file:stream', 'dir\\file'])
def test_dependency_extraction_rejects_unsafe_paths(tmp_path, name):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as target:
        target.writestr(name, b'content')
    with pytest.raises(ValueError):
        fetch_release_inputs.extract(archive, tmp_path / 'destination', {name: digest(b'content')})
    assert not (tmp_path / 'destination').exists()


def test_dependency_extraction_checks_contents(tmp_path):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as target:
        target.writestr('Notices/license.txt', b'content')
    expected = {'Notices/license.txt': digest(b'content')}
    fetch_release_inputs.extract(archive, tmp_path / 'valid', expected)
    with pytest.raises(ValueError, match='checksum'):
        fetch_release_inputs.extract(archive, tmp_path / 'invalid', {'Notices/license.txt': digest(b'other')})


@pytest.fixture
def verified_build(tmp_path, monkeypatch):
    payload = tmp_path / 'dist/Cadence'
    payload.mkdir(parents=True)
    (payload / 'Cadence.exe').write_bytes(b'fixture')
    identity = {'source_sha256': 'matching-source'}
    monkeypatch.setattr(release, 'source_identity', lambda: identity)
    (tmp_path / 'pytest.xml').write_text('<testsuite failures="0"/>')
    evidence = {'status': 'passed', 'source': identity.copy(), 'payload': {'Cadence.exe': digest(b'fixture')},
                'pytest_xml_sha256': build_inputs.sha256(tmp_path / 'pytest.xml'), 'smoke': {}}
    for language in ('fr', 'en'):
        folder = tmp_path / f'smoke-{language}'
        folder.mkdir()
        result = {'status': 'passed', 'frozen': True, 'language': language,
                  'native_mixed_rates': True, 'background_audio': True, 'reference_sequence': True,
                  'timecode_overlay': True, 'native_pixels': True}
        (folder / 'result.json').write_text(json.dumps(result))
        evidence['smoke'][language] = build_inputs.sha256(folder / 'result.json')
    (tmp_path / 'verification.json').write_text(json.dumps(evidence))
    return tmp_path, payload, identity


@pytest.mark.parametrize('change', ['source', 'payload', 'pytest', 'smoke'])
def test_release_rejects_stale_or_modified_build(verified_build, change):
    directory, payload, identity = verified_build
    release.validate_build(directory, payload)
    if change == 'source':
        identity['source_sha256'] = 'changed'
    elif change == 'payload':
        (payload / 'Cadence.exe').write_bytes(b'changed')
    elif change == 'pytest':
        (directory / 'pytest.xml').write_text('changed')
    else:
        (directory / 'smoke-fr/result.json').write_text('{}')
    with pytest.raises(ValueError):
        release.validate_build(directory, payload)
