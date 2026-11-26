# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import struct
import threading

import av
import numpy as np
import pytest

from drawing import DrawingKey, Mark
from media import Cancelled, export_video, prepare_media
from model import Document, sample_at
from studio_export import PROFILES
from test_drawing import application


@pytest.fixture()
def scene(tmp_path, monkeypatch):
    monkeypatch.setenv('CADENCE_CACHE', str(tmp_path/'cache'))
    doc = Document()
    doc.append_media([prepare_media(Path(__file__).resolve().parents[1] / 'assets/Demonstration.mp4')])
    mark = Mark(points=((.25,.25,1.),), color='#804020', opacity=.5, size=.12)
    doc.fps = Fraction(24000,1001)
    doc.state = replace(doc.state, segments=(replace(doc.state.segments[0], end=4),), audio_segments=None,
                        drawings=(DrawingKey(1,3,(mark,)),))
    return doc


def rgba_pixel(path, x=.25, y=.25):
    with av.open(str(path)) as movie:
        rgba = next(movie.decode(video=0)).to_ndarray(format='rgba')
        return rgba[int(rgba.shape[0]*y),int(rgba.shape[1]*x)].astype(int)


def exr_attributes(path):
    with path.open('rb') as file:
        assert file.read(4) == b'\x76\x2f\x31\x01'
        file.read(4)
        def string():
            value = bytearray()
            while byte := file.read(1):
                if byte == b'\0': break
                value.extend(byte)
            return bytes(value)
        attrs = {}
        while name := string():
            string()
            attrs[name] = file.read(struct.unpack('<I',file.read(4))[0])
        return attrs


@pytest.mark.parametrize('key',['png','tga','exr'])
def test_image_sequences_include_holds_alpha_and_start_number(application, scene, tmp_path, key):
    ext=PROFILES[key].extension
    dest=tmp_path/('révision 50%'+ext)
    first=Path(export_video(scene.state,scene.media,scene.fps,dest,profile=key,first_frame=99,drawings_only=True))
    assert first.parent==tmp_path/('révision 50%-'+key)
    images=sorted(first.parent.iterdir())
    assert [im.name for im in images]==[f'révision 50%.{i:04d}{ext}' for i in range(99,103)]
    if key!='exr':
        assert rgba_pixel(first)[3]==0
        for im in images[1:3]:
            assert np.max(np.abs(rgba_pixel(im)-[128,64,32,127])) <= 2
            assert rgba_pixel(im,.25,.75)[3]==0
        assert rgba_pixel(images[3])[3]==0
        if key=='tga': assert images[1].read_bytes()[2] == 10
    else:
        attrs=exr_attributes(images[1])
        assert attrs[b'compression']==b'\x03'
        channels=attrs[b'channels']
        for channel in (b'A',b'B',b'G',b'R'):
            assert channel+b'\0\x01\0\0\0' in channels  # HALF channel declaration
        with av.open(str(images[1])) as source:
            frame=next(source.decode(video=0))
            assert frame.format.name=='gbrapf16le'
            pixel=[np.frombuffer(p,dtype='<f2').reshape(frame.height,p.line_size//2)[frame.height//4,frame.width//4]
                   for p in frame.planes]
        alpha=pixel[3]
        assert alpha==pytest.approx(.5,abs=.008)
        assert pixel[2]==pytest.approx(.216*alpha,abs=.003)
    with pytest.raises(ValueError,match='existe déjà'):
        export_video(scene.state,scene.media,scene.fps,dest,profile=key)
    assert sorted(first.parent.iterdir()) == images


@pytest.mark.parametrize('key,profile,codec',[('prores-hq','HQ','prores'),('prores-4444','4444','prores'),
                                              ('dnxhr','DNXHR HQ','dnxhd')])
def test_movie_profiles_cadence_and_pcm(application,scene,tmp_path,key,profile,codec):
    path=tmp_path/(key+'.mov')
    export_video(scene.state,scene.media,scene.fps,path,profile=key)
    with av.open(str(path)) as movie:
        video=movie.streams.video[0]
        assert video.codec_context.name==codec and video.profile.upper()==profile
        assert video.average_rate==scene.fps
        frames=list(movie.decode(video=0))
        assert len(frames)==4
        with av.open(scene.media[scene.state.segments[0].media]['path']) as source:
            expected=next(source.decode(video=0)).to_ndarray(format='rgb24')
        rgb=frames[0].to_ndarray(format='rgb24')
        assert np.abs(rgb.astype(int)-expected).mean()<4
    with av.open(str(path)) as movie:
        assert movie.streams.audio[0].codec_context.name=='pcm_s16le'
        assert sum(f.samples for f in movie.decode(audio=0))==sample_at(4,scene.fps)
    if key=='prores-4444':
        export_video(scene.state,scene.media,scene.fps,path,profile=key,drawings_only=True)
        with av.open(str(path)) as movie:
            assert not movie.streams.audio
            frames=[f.to_ndarray(format='rgba') for f in movie.decode(video=0)]
        assert frames[0][135,240,3]==0 and frames[3][135,240,3]==0
        assert np.max(np.abs(frames[1][135,240].astype(int)-[128,64,32,127]))<=4
        assert np.array_equal(frames[1],frames[2])


def test_sequence_cancel_and_missing_source_drawing_pass(application,scene,tmp_path):
    for info in scene.media.values(): info['path']=str(tmp_path/'missing.mov')
    dest=tmp_path/'notes.png'
    cancel=threading.Event(); cancel.set()
    with pytest.raises(Cancelled):
        export_video(scene.state,scene.media,scene.fps,dest,cancel=cancel,drawings_only=True)
    assert not (tmp_path/'notes-png').exists()
    assert Path(export_video(scene.state,scene.media,scene.fps,dest,drawings_only=True)).is_file()


def test_movie_alpha_survives_full_sequence_export(application,scene,tmp_path):
    film = tmp_path/'overlay.mov'
    export_video(scene.state,scene.media,scene.fps,film,profile='prores-4444',drawings_only=True)
    source = Document()
    source.fps = scene.fps
    source.append_media([prepare_media(film)])
    dest = tmp_path/'rgba.png'
    first = Path(export_video(source.state,source.media,source.fps,dest))
    frames = sorted(first.parent.glob('*.png'))
    assert rgba_pixel(frames[0])[3]==0
    sample = rgba_pixel(frames[1])
    assert np.max(np.abs(sample-[128,64,32,127])) <= 4
    alpha = sample[3]/255
    for background in (0,255):
        composed = sample[:3]*alpha + background*(1-alpha)
        assert np.max(np.abs(composed-(np.array([128,64,32])*.5+background*.5)))<4


def test_sequence_sidecar_media_reference(scene,tmp_path):
    import json
    from review_otio import write_otio
    first = tmp_path/'révision 35%.0100.png'
    write_otio(tmp_path/'notes.otio',scene,first,image_sequence=True)
    stack=json.loads((tmp_path/'notes.otio').read_text('utf8'))['tracks']
    ref=stack['children'][0]['children'][0]['media_references']['DEFAULT_MEDIA']
    assert ref['OTIO_SCHEMA']=='ImageSequenceReference.1' and ref['start_frame']==100
    assert ref['available_range']['duration']['value']==4 and ref['rate']==float(scene.fps)
    assert ref['target_url_base']+ref['name_prefix']+'0100'+ref['name_suffix']==first.as_uri()


@pytest.mark.parametrize('language',['fr','en'])
def test_profile_dialog_roundtrip(application,scene,language,monkeypatch):
    from PySide6.QtWidgets import QComboBox
    from export_dialog import ExportDialog
    import ui_text
    monkeypatch.setattr(ui_text,'_language',language)
    dialog=ExportDialog(None,scene)
    dialog.show()
    try:
        choices=dialog.findChild(QComboBox,'fileTypeCombo')
        for key,fmt in PROFILES.items():
            text=ui_text.tr(fmt.label)
            choices.setCurrentIndex(choices.findText(text))
            dialog.change_format(text)
            application.processEvents()
            assert Path(dialog.selectedFiles()[0]).suffix==fmt.extension
            assert dialog.first_frame.isVisible()==fmt.sequence
            assert dialog.drawings_only.isVisible()==fmt.alpha
            assert dialog.render_options()['profile']==key
            if fmt.sequence:
                dialog.first_frame.setValue(25)
                assert '.0025'+fmt.extension in dialog.sequence_label.text()
            if fmt.alpha:
                dialog.drawings_only.setChecked(True)
                assert dialog.render_options()['drawings_only']
        dialog.change_format(text)
        assert not dialog.render_options()['drawings_only']
    finally:
        dialog.close()
