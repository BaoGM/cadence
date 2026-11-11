# SPDX-License-Identifier: GPL-3.0-only
import json, logging
from preferences import preference_path, write_file


def path(): return preference_path().with_name('playback.json')


def load(window):
    try: data=json.loads(path().read_text(encoding='utf-8'))
    except (OSError,ValueError): data={}
    if not isinstance(data,dict): data={}
    volume=data.get('volume',80)
    if type(volume) not in (int,float) or not 0<=volume<=100: volume=80
    window.volume.setValue(round(volume)); window.volume.setMuted(data.get('muted') is True)
    window.timeline.set_units('frames' if data.get('units')=='frames' else 'time')
    window.master_volume()
    window.timecode_overlay.set_position(data.get('timecode_position',[.5,1]))
    window.timecode_overlay.set_locked(data.get('timecode_locked') is True)
    from navigation_modes import set_key_step
    set_key_step(window,data.get('key_step') is True)


def save(window):
    try: write_file(path(),dict(volume=window.volume.value(),muted=window.volume.muted,units=window.timeline.units,key_step=window.key_step,timecode_position=window.timecode_overlay.position(),timecode_locked=window.timecode_overlay.locked))
    except OSError: logging.exception('Cannot save playback preferences')
