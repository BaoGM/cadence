# SPDX-License-Identifier: GPL-3.0-only
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from media import ffmpeg


def pulse(*args):
    env = os.environ.copy()
    env.pop('LD_LIBRARY_PATH', None)
    if env.get('LD_LIBRARY_PATH_ORIG'): env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
    return subprocess.check_output(['pactl', *args], env=env, text=True, timeout=5).strip()


def sources(system, microphone):
    selected = []
    if system:
        name = pulse('get-default-sink')
        sinks = json.loads(pulse('--format=json', 'list', 'sinks'))
        sink = next(item for item in sinks if item['name'] == name)
        monitor = sink.get('monitor_source_name') or sink.get('monitor_source')
        if not isinstance(monitor, str): raise RuntimeError('Source de sortie audio indisponible.')
        selected.append(monitor)
    if microphone:
        name = pulse('get-default-source')
        devices = json.loads(pulse('--format=json', 'list', 'sources'))
        device = next(item for item in devices if item['name'] == name)
        if (device.get('monitor_of_sink_name') or device.get('monitor_of_sink') not in (None, 4294967295)
                or device.get('properties', {}).get('device.class') == 'monitor'):
            raise RuntimeError('Aucun microphone par défaut disponible.')
        selected.append(name)
    return selected


class Track:
    def __init__(self, device, path):
        self.device = device; self.path = path; self.first_time = None; self.error = None
        self.proc = None; self.log = None

    def start(self):
        self.log = tempfile.TemporaryFile()
        self.started = time.time()
        self.proc = subprocess.Popen([ffmpeg(), '-hide_banner', '-nostats', '-n',
            '-f', 'pulse', '-wallclock', '1', '-sample_rate', '48000', '-channels', '2',
            '-i', self.device, '-c:a', 'pcm_s16le', str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)

    def stop(self):
        try:
            if self.proc:
                process, self.proc = self.proc, None
                try:
                    process.communicate(b'q\n', timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try: process.communicate(timeout=3)
                    except subprocess.TimeoutExpired: process.kill(); process.communicate()
                self.log.seek(0); detail = self.log.read().decode(errors='replace')
                match = re.search(r'start:\s*([\d.]+)', detail)
                self.first_time = float(match[1]) if match else self.started
                if process.returncode or not self.path.exists(): self.error = detail[-2000:] or 'Audio recording failed'
        finally:
            if self.log: self.log.close(); self.log = None


class AudioCapture:
    def __init__(self, system=False, microphone=False):
        self.tracks = []; self.temp = tempfile.TemporaryDirectory(prefix='cadence-audio-')
        try:
            self.tracks = [Track(device, Path(self.temp.name) / f'{index}.wav')
                           for index, device in enumerate(sources(system, microphone))]
        except Exception as exc:
            self.close()
            raise RuntimeError('Impossible d’ouvrir la source sonore sélectionnée. Vérifiez les périphériques audio et le service PipeWire / PulseAudio.\n' + str(exc)) from exc

    def start(self):
        try:
            for track in self.tracks: track.start()
        except Exception:
            self.stop(); raise

    def stop(self):
        for track in self.tracks: track.stop()

    def close(self):
        try: self.stop()
        finally: self.temp.cleanup()
