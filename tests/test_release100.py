# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
from types import SimpleNamespace
import json, shutil
import pytest
from test_drawing import application


@pytest.mark.parametrize('saved',[[],None,42,'english',{'language':[]}])
def test_invalid_preferences_do_not_prevent_launch(application,tmp_path,monkeypatch,saved):
    import ui_text
    from app import MainWindow
    path=tmp_path/'preferences.json'; path.write_text(json.dumps(saved),encoding='utf-8')
    monkeypatch.setenv('CADENCE_PREFS',str(path)); monkeypatch.delenv('CADENCE_LANGUAGE',raising=False)
    window=MainWindow()
    try:
        assert ui_text.language()=='fr'
        assert window.windowTitle().startswith('Cadence')
    finally: window.close()


def test_mux_failure_preserves_other_recordings_and_cleans_own_temp(tmp_path,monkeypatch):
    import capture_audio
    video=tmp_path/'recording.mp4'
    shutil.copy(Path(__file__).resolve().parents[1]/'assets/Demonstration.mp4',video)
    original=video.read_bytes()
    neighbour=tmp_path/'recording-avec-son.mp4'; neighbour.write_bytes(b'existing recording')
    outputs=[]
    def fail(args,**kwargs):
        output=Path(args[-1]); outputs.append(output)
        assert output.is_file() and output!=neighbour
        output.write_bytes(b'incomplete output')
        return SimpleNamespace(returncode=1,stderr=b'encoding failed')
    monkeypatch.setattr(capture_audio.subprocess,'run',fail)
    track=SimpleNamespace(path=tmp_path/'audio.wav',first_time=100.,error=None)
    monkeypatch.setattr(capture_audio,'ffmpeg',lambda:'ffmpeg.exe')
    with pytest.raises(RuntimeError,match='encoding failed'): capture_audio.mux_audio(video,[track],100.)
    assert video.read_bytes()==original and neighbour.read_bytes()==b'existing recording'
    assert outputs and all(not path.exists() for path in outputs)


def test_non_object_cache_manifest_is_regenerated(tmp_path,monkeypatch):
    from media import prepare_media
    monkeypatch.setenv('CADENCE_CACHE',str(tmp_path/'cache'))
    source=Path(__file__).resolve().parents[1]/'assets/Demonstration.mp4'
    first=prepare_media(source)
    manifest=Path(first['proxy']).parent/'media.json'
    manifest.write_text('[]',encoding='utf-8')
    restored=prepare_media(source)
    assert restored['frames']==first['frames'] and Path(restored['audio']).is_file()
    assert json.loads(manifest.read_text(encoding='utf-8'))['id']==first['id']
