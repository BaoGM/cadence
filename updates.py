# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, build_opener

REPOSITORY = 'https://github.com/BaoGM/cadence'
RELEASES_URL = 'https://api.github.com/repos/BaoGM/cadence/releases?per_page=100'
MAX_PACKAGE = 2 * 1024**3

class UpdateCancelled(Exception):
    pass

def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('Invalid release version')
    return tuple(map(int, value.split('.')))

def checked_url(url):
    parts = urlparse(url)
    if parts.scheme != 'https' or parts.hostname not in (
        'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'
    ) or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError('Untrusted update URL')
    return url

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return super().redirect_request(request, fp, code, message, headers, checked_url(new_url))

def open_url(url):
    request = Request(checked_url(url), headers={
        'User-Agent': 'Cadence-update-check', 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2026-03-10',
    })
    return build_opener(HTTPSHandler(), SafeRedirect()).open(request, timeout=15)

def read_json(url, limit=4*1024*1024):
    with open_url(url) as response:
        raw = response.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Update metadata is too large')
    return json.loads(raw)

@dataclass(frozen=True)
class Release:
    version: str
    prerelease: bool
    filename: str
    size: int
    digest: str
    tag: str = ''

    @property
    def page(self):
        return REPOSITORY + '/releases/tag/' + (self.tag or 'v'+self.version)

    @property
    def base(self):
        return REPOSITORY + '/releases/download/' + (self.tag or 'v'+self.version) + '/'

    @property
    def url(self):
        return self.base + self.filename

def select_release(releases, current, installed, previews=False, *, studio=False):
    if not isinstance(releases, list):
        raise ValueError('Invalid release list')
    candidates = []
    for item in releases:
        if not isinstance(item, dict) or item.get('draft') or (item.get('prerelease') and not previews):
            continue
        tag = item.get('tag_name', '')
        try:
            suffix = '-windows-studio2' if studio else '-windows'
            version = tag.removeprefix('v').removesuffix(suffix)
            valid_tags = ('v'+version+suffix,) if studio else ('v'+version, 'v'+version+suffix)
            if tag not in valid_tags or version_tuple(version) <= version_tuple(current):
                continue
        except (ValueError, AttributeError):
            continue
        filename = f'Cadence-{version}-Windows.zip'
        assets = {a.get('name'): a for a in item.get('assets', []) if isinstance(a, dict) and a.get('state') == 'uploaded'}
        asset = assets.get(filename)
        if not asset or f'Cadence-{version}-update.json' not in assets:
            continue
        size = asset.get('size')
        if type(size) is not int or not 0 < size <= MAX_PACKAGE:
            continue
        digest = asset.get('digest') or ''
        if digest and not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
            continue
        candidates.append(Release(version, bool(item.get('prerelease')), filename, size, digest[7:].lower(),tag))
    return max(candidates, key=lambda r: version_tuple(r.version), default=None)

def check(current, installed, previews=False):
    return select_release(read_json(RELEASES_URL), current, installed, previews, studio=True)

def package_descriptor(release):
    from update_store import verify_signature,signed_message
    manifest=read_json(release.base+f'Cadence-{release.version}-update.json',65536)
    if manifest['version']!=release.version or manifest['size']!=release.size or manifest['preview'] is not release.prerelease:
        raise ValueError('Wrong update descriptor')
    digest=manifest['sha256']
    verify_signature(signed_message(release.version,release.size,digest,release.prerelease),manifest['signature'])
    if release.digest and digest!=release.digest: raise ValueError('Conflicting SHA-256 checksums')
    return manifest

def download(release, directory, cancel, progress, descriptor=None):
    digest=(descriptor or package_descriptor(release))['sha256']
    if cancel.is_set():
        raise UpdateCancelled()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='cadence-', dir=directory))
    partial = staging / (release.filename + '.part')
    target = staging / release.filename
    try:
        total = 0
        hasher = hashlib.sha256()
        deadline = time.monotonic() + 1800
        with open_url(release.url) as response, partial.open('xb') as output:
            while True:
                if cancel.is_set():
                    raise UpdateCancelled()
                if time.monotonic() > deadline:
                    raise TimeoutError('Download deadline exceeded')
                chunk = response.read(256*1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > release.size:
                    raise ValueError('Downloaded package exceeds expected size')
                output.write(chunk); hasher.update(chunk)
                progress(total*100//release.size)
        if cancel.is_set():
            raise UpdateCancelled()
        if total != release.size or hasher.hexdigest() != digest:
            raise ValueError('Downloaded package failed integrity verification')
        partial.replace(target)
        return target, digest
    except BaseException:
        partial.unlink(missing_ok=True)
        if not any(staging.iterdir()):
            staging.rmdir()
        raise

def verify_package(path, digest):
    with Path(path).open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
            raise ValueError('Downloaded package changed after verification')

def installed_copy(executable):
    return (Path(executable).resolve().parent / 'uninstall' / 'unins000.exe').is_file()

