# SPDX-License-Identifier: GPL-3.0-only
import json, logging, math, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QLockFile, QPointF
from model import Document
from preferences import preference_path
from workspace_modes import encoded, decoded
from ui_text import tr


def session_path():
    return preference_path().with_name('last_session.json')


def read_session(path):
    path=Path(path)
    if path.stat().st_size>64*1024*1024: raise ValueError('Fichier de session trop volumineux.')
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or data.get('format')!='cadence-session' or data.get('version')!=1:
        raise ValueError('Fichier de session incompatible.')
    project=data.get('project_path')
    if project is not None and not isinstance(project,str): raise ValueError('Chemin de projet invalide.')
    doc=Document.from_data(data['document'],project)
    if data.get('dirty') is True: doc.saved_signature=None
    return data,doc


def encode_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),default=lambda item:{field.name:getattr(item,field.name) for field in fields(item)})


class SnapshotEncoder:
    def __init__(self):
        self.cached={}; self.keys={}

    def state(self,state):
        result=[]
        for field in fields(state):
            value=getattr(state,field.name); found=self.cached.get(field.name)
            if found is not None and found[0] is value: encoded=found[1]
            elif field.name=='drawings':
                retained={}; parts=[]; deadline=time.perf_counter()+.002
                for key in value:
                    old=self.keys.get(id(key))
                    text=old[1] if old is not None and old[0] is key else encode_json(key)
                    retained[id(key)]=(key,text); parts.append(text)
                    if time.perf_counter()>=deadline:
                        time.sleep(.001); deadline=time.perf_counter()+.002
                self.keys=retained; encoded='['+','.join(parts)+']'
            else: encoded=encode_json(value)
            self.cached[field.name]=(value,encoded); result.append(encode_json(field.name)+':'+encoded)
        return '{'+','.join(result)+'}'


def write_snapshot(path,document,view,encoder=None):
    state,media,fps,review,project,dirty=document
    payload=dict(format='cadence-session',version=1,updated=datetime.now(timezone.utc).isoformat(),
                 project_path=project,dirty=dirty,view=view)
    document=dict(format='cadence-studio',version=15 if len(review.get('references',[]))>1 else 14 if review.get('reference_cadence') or any(m.get('cadence') for m in media.values()) else 13 if any(m.get('has_video') is False for m in media.values()) else 12 if state.frame_markers else 11,
                  media=list(media.values()),fps=str(fps),comparison=review)
    encoded_state=(encoder or SnapshotEncoder()).state(state)
    text=encode_json(payload)[:-1]+',"document":'+encode_json(document)[:-1]+',"state":'+encoded_state+'}}'
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp'); temporary.write_text(text,encoding='utf-8'); temporary.replace(path)


def number(data,key,default,lo,hi):
    value=data.get(key,default)
    return max(lo,min(hi,float(value))) if type(value) in (int,float) and math.isfinite(value) else default


class SessionRecovery(QObject):
    def __init__(self,window):
        super().__init__(window); self.w=window; self.path=session_path(); self.future=None; self.fingerprint=None
        self.pending=False; self.closed=False; self.pool=None; self.encoder=SnapshotEncoder()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=QLockFile(str(self.path)+'.lock'); self.owner=self.lock.tryLock(0)
        if self.owner: self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='cadence-session')
        self.timer=QTimer(self); self.timer.setInterval(2000); self.timer.timeout.connect(self.checkpoint)
        if self.owner: self.timer.start()

    def view(self):
        w=self.w; d=w.drawing; v=w.viewer; t=w.timeline
        panels={k:not p.isHidden() for k,p in w.workspaces.panels.items()}
        layout=w.saveState()
        if w.video_fullscreen:
            panels.update(w.before_fullscreen); panels['timecode']=not w.timecode_overlay.isHidden(); panels['library']=w.library_was_visible; layout=w.normal_dock_state
        return dict(mode=w.workspaces.mode,layout=encoded(layout),editable=w.layout_editable,
                    panels=panels,simple=t.simple,
                    units=t.units,timeline_zoom=t.zoom,timeline_start=t.view_start,selection_track=t.selection_track,
                    zoom=v.zoom,pan=[v.pan.x(),v.pan.y()],angle=v.angle,volume=w.volume.value(),muted=w.volume.muted,
                    loop=w.playback_mode,copy_audio=w.copy_audio.isChecked(),leave_gap=w.leave_gap.isChecked(),
                    link_tracks=w.link_tracks.isChecked(),apply_exposure=w.apply_export.isChecked(),
                    drawings_visible=d.visible.isChecked(),drawings_export=d.export.isChecked(),
                    onion=d.onion.isChecked(),before=d.before.value(),after=d.after.value(),ghost=d.ghost.value(),
                    brush_size=d.size.value(),brush_opacity=d.opacity.value(),sensitivity=d.sensitivity.value(),color=d.wheel.color())

    def checkpoint(self,wait=False):
        if not self.owner or self.closed or self.pending or self.w.job or not self.w.doc.media: return
        if self.future:
            if not wait and not self.future.done(): return
            try: self.future.result()
            except Exception as error: logging.exception('Session recovery write failed: %s',error); self.fingerprint=None
            self.future=None
        w=self.w; doc=w.doc; view=self.view(); review=w.comparison_snapshot()
        key=(id(doc),id(doc.state),tuple((k,id(m)) for k,m in doc.media.items()),doc.project_path,doc.dirty,view,review)
        if key==self.fingerprint: return
        self.fingerprint=key
        document=(doc.state,{k:dict(m) for k,m in doc.media.items()},doc.fps,review,doc.project_path,doc.dirty)
        self.future=self.pool.submit(write_snapshot,self.path,document,view,self.encoder)
        if wait:
            try: self.future.result()
            except Exception as error: logging.exception('Session recovery write failed: %s',error); self.fingerprint=None
            self.future=None

    def offer(self):
        if not self.owner or self.closed or self.w.job or self.w.doc.media or not self.path.exists(): return
        try: data,doc=read_session(self.path)
        except Exception as error:
            logging.exception('Session recovery read failed: %s',error)
            self.w.error(tr('La session précédente est illisible. Aucun projet n’a été modifié.')); return
        self.pending=True
        name=Path(doc.project_path).name if doc.project_path else next((m.get('name','') for m in doc.media.values()),'')
        from dialogs import ConfirmationDialog
        box=ConfirmationDialog(self.w,tr('Restaurer la dernière session'),tr('Retrouver la session précédente ?'),name)
        choice=box.exec(); box.deleteLater()
        if choice!=1:
            if choice==2:
                try: self.path.unlink(missing_ok=True)
                except OSError as error: logging.warning('Session refusal: %s',error)
            self.pending=False; return
        self.restore(data,doc)

    def restore(self,data,doc):
        w=self.w; quality=w.preferences.get('preview_quality','native')
        self.pending=True
        def prepare(progress,cancel):
            from media import prepare_media, validate_media, Cancelled
            for key,media in list(doc.media.items()):
                validate_media(media)
                refreshed=prepare_media(media['path'],doc.fps,progress,cancel,quality=quality,cadence=media.get('cadence'),defer_audio=True)
                refreshed['id']=key; doc.media[key]=refreshed
            from reference_sequence import restore
            restore(doc,quality,progress,cancel)
            return doc
        def success(restored):
            w.install_doc(restored); self.apply_view(data.get('view',{})); self.fingerprint=None
        w.begin_task('Restauration de la session',prepare,success)
        if w.job: w.job.finished.connect(self.restore_finished)
        else: self.pending=False

    def restore_finished(self): self.pending=False

    def apply_view(self,data):
        if not isinstance(data,dict): return
        w=self.w; d=w.drawing; t=w.timeline; v=w.viewer; ws=w.workspaces
        mode=data.get('mode','read'); mode=mode if mode in ('read','edit') else 'read'
        panels=data.get('panels',{})
        if isinstance(panels,dict):
            for key in ws.panels:
                if type(panels.get(key)) is bool: ws.profiles[mode][key]=panels[key]
        if type(data.get('simple')) is bool: ws.simple[mode]=data['simple']
        if not decoded(data.get('layout')).isEmpty(): ws.layouts[mode]=data['layout']
        ws.editable[mode]=data.get('editable') is True; ws.apply(mode)
        t.zoom=number(data,'timeline_zoom',1,1,max(1,w.doc.state.length/2))
        t.view_start=number(data,'timeline_start',0,0,w.doc.state.length); t.clamp_view()
        t.selection_track=data.get('selection_track') if data.get('selection_track') in ('video','audio','drawing') else 'video'
        v.zoom=number(data,'zoom',1,.05,30); v.angle=number(data,'angle',0,-100000,100000)
        pan=data.get('pan'); pan=pan if isinstance(pan,list) and len(pan)==2 else [0,0]
        v.pan=QPointF(number({'x':pan[0]},'x',0,-100000,100000),number({'y':pan[1]},'y',0,-100000,100000))
        w.playback_mode='loop' if data.get('loop')=='loop' else 'once'
        for key,control in [('copy_audio',w.copy_audio),('leave_gap',w.leave_gap),('link_tracks',w.link_tracks),('apply_exposure',w.apply_export),('drawings_visible',d.visible),('drawings_export',d.export),('onion',d.onion)]:
            if type(data.get(key)) is bool: control.setChecked(data[key])
        for key,control in [('before',d.before),('after',d.after),('ghost',d.ghost),('brush_size',d.size),('brush_opacity',d.opacity),('sensitivity',d.sensitivity)]:
            control.setValue(number(data,key,control.value(),control.minimum(),control.maximum()))
        color=data.get('color')
        if isinstance(color,str): d.wheel.set_color(color)
        w.follow_position=w.doc.state.position; w.refresh(); w.request_frame(); ws.capture(); ws.save()

    def close(self):
        if self.closed: return
        self.checkpoint(wait=True); self.closed=True; self.timer.stop()
        if self.pool: self.pool.shutdown(wait=True)
        if self.owner: self.lock.unlock()
