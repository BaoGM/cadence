# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from ui_text import tr
import json, os
from pathlib import Path
from PySide6.QtCore import Qt,QObject,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QGroupBox,QTabWidget,QWidget,QTableWidget,QTableWidgetItem,QPushButton,QComboBox,QCheckBox,QLabel,QDialogButtonBox,QFileDialog,QMessageBox,QHeaderView)

from cache_ram import default_cache_mb,maximum_cache_mb
from shortcut_defaults import REVISION,migrate
from platform_support import WINDOWS, config_directory

MODIFIERS=['Aucun','Ctrl','Shift','Alt','Ctrl+Shift','Ctrl+Alt','Shift+Alt','Ctrl+Shift+Alt']

def default_canvas():
    return {name:dict(modifiers=mod,axis=axis,invert_x=False,invert_y=False) for name,mod,axis in [('zoom','Ctrl','x'),('rotate','Shift','y'),('pan','Aucun','x')]}

def modifier_name(mods):
    return '+'.join(name for flag,name in [(Qt.KeyboardModifier.ControlModifier,'Ctrl'),(Qt.KeyboardModifier.ShiftModifier,'Shift'),(Qt.KeyboardModifier.AltModifier,'Alt')] if mods&flag) or 'Aucun'

def default_renderer():
    return 'direct3d' if os.name=='nt' else 'opengl'

def preferred_renderer(data):
    renderer=data.get('video_renderer',default_renderer())
    if renderer=='direct3d' and not WINDOWS: return default_renderer()
    if renderer=='opengl' and data.get('video_renderer_version')!=2:
        return default_renderer()
    return renderer if renderer in ('direct3d','opengl','software') else default_renderer()

def defaults(registry):
    return dict(format='cadence-shortcuts',version=1,shortcut_defaults_revision=REVISION,shortcuts={key:value[1] for key,value in registry.items()},canvas=default_canvas(),scrub_pixels=4.,language='fr',clear_cache_on_exit=False,preview_quality='native',scrub_audio=True,tooltips=True,auto_update_check=True,update_previews=False,video_renderer=default_renderer(),video_renderer_version=2,ram_cache_mb=default_cache_mb())

def validate(data,registry):
    if not isinstance(data,dict) or data.get('format')!='cadence-shortcuts' or data.get('version')!=1: raise ValueError('Format de raccourcis incompatible.')
    result=defaults(registry); supplied=data.get('shortcuts',{})
    if not isinstance(supplied,dict): raise ValueError('Liste de raccourcis invalide.')
    supplied=dict(supplied)
    # Preserve customized shortcuts when older labels used long dash separators.
    for old,value in list(supplied.items()):
        if not isinstance(old,str): continue
        key=old.replace('\u2014','-').replace('\u2013','-')
        if key not in supplied: supplied[key]=value
    aliases={'Dessin/Pinceau':'Outils/Pinceau','Dessin/Gomme':'Outils/Gomme','Dessin/Lasso / déplacement':'Outils/Lasso / déplacement','Dessin/Texte Arial':'Outils/Texte','Dessin/Activer le dessin':'Outils/Curseur','Dessin/Activer le calque':'Outils/Curseur'}
    aliases['Fichier/Enregistrer le projet']='Fichier/Enregistrer'
    aliases['Fichier/Associer les fichiers .cadence à cette version']='Fichier/Associer les vidéos et projets à cette version'
    aliases['Dessin/Ajouter une clé vide']='Dessin/Ajouter un marqueur'
    aliases['Outils/Redimensionner le clip']='Outils/Transformer la sélection ou le clip'
    aliases['Affichage/Liste de lecture et médias']='Affichage/Afficher la liste de lecture'
    aliases['Dessin/Afficher les outils de dessin']='Affichage/Afficher les outils de dessin'
    aliases['Dessin/Copier la clé au curseur']='Dessin/Dupliquer la clé au curseur'
    aliases['Comparaison/Afficher les réglages']='Affichage/Afficher les réglages de comparaison'
    aliases['Comparaison/Ouvrir une référence B…']='Comparaison/Ajouter des références B…'
    aliases['Édition/Raccourcis et navigation…']='Fichier/Options…'
    for title in ('Clé précédente','Clé suivante'): aliases['Dessin/'+title]='Lecture/'+title
    aliases['Lecture/Basculer le pas image / clé']='Lecture/Basculer le pas clé / image'
    for old,new in [('Copier la clé','Copier les clés'),('Couper la clé','Couper les clés'),('Coller la clé','Coller les clés')]: aliases['Dessin/'+old]='Dessin/'+new
    for old,new in aliases.items():
        if old in supplied and new not in supplied: supplied[new]=supplied[old]
    if supplied.get('Comparaison/Activer la comparaison')=='C' and 'Outils/Recadrer le clip' not in supplied:
        supplied['Comparaison/Activer la comparaison']='Shift+C'
    supplied=migrate(supplied,registry,data.get('shortcut_defaults_revision'))
    sequences=[]
    for key,default in result['shortcuts'].items():
        value=supplied.get(key,default)
        # A newly introduced default must not invalidate older custom shortcuts.
        if key not in supplied and value:
            candidate=QKeySequence(value,QKeySequence.SequenceFormat.PortableText)
            for other,saved in supplied.items():
                if other!=key and other in registry and isinstance(saved,str) and saved:
                    sequence=QKeySequence(saved,QKeySequence.SequenceFormat.PortableText)
                    if candidate.matches(sequence)!=QKeySequence.SequenceMatch.NoMatch or sequence.matches(candidate)!=QKeySequence.SequenceMatch.NoMatch:
                        value=''; break
        if not isinstance(value,str) or len(value)>160: raise ValueError('Raccourci invalide : '+key)
        sequence=QKeySequence(value,QKeySequence.SequenceFormat.PortableText)
        portable=sequence.toString(QKeySequence.SequenceFormat.PortableText)
        if value and (sequence.isEmpty() or not portable or any(sequence[i].key()==Qt.Key.Key_unknown for i in range(sequence.count()))): raise ValueError('Raccourci invalide : '+key)
        if portable:
            for other,otherkey in sequences:
                if sequence.matches(other)!=QKeySequence.SequenceMatch.NoMatch or other.matches(sequence)!=QKeySequence.SequenceMatch.NoMatch:
                    raise ValueError(f'Conflit de raccourcis : {key} et {otherkey}.')
            sequences.append((sequence,key))
        result['shortcuts'][key]=portable
    canvas=data.get('canvas',result['canvas'])
    if not isinstance(canvas,dict): raise ValueError('Gestes du canvas invalides.')
    for key,default in result['canvas'].items():
        config=canvas.get(key,default)
        if not isinstance(config,dict) or config.get('modifiers') not in MODIFIERS or config.get('axis') not in ('x','y') or any(type(config.get(x)) is not bool for x in ('invert_x','invert_y')): raise ValueError('Geste du canvas invalide : '+key)
        result['canvas'][key]={field:config[field] for field in default}
    if len({v['modifiers'] for v in result['canvas'].values()})!=3: raise ValueError('Chaque geste au bouton central doit utiliser une combinaison différente.')
    sensitivity=data.get('scrub_pixels',4.)
    if isinstance(sensitivity,bool) or not isinstance(sensitivity,(int,float)) or not .25<=sensitivity<=100: raise ValueError('La sensibilité du scrub doit être comprise entre 0,25 et 100 pixels par image.')
    result['scrub_pixels']=float(sensitivity)
    result['language']=data.get('language','fr') if data.get('language','fr') in ('fr','en') else 'fr'
    result['clear_cache_on_exit']=data.get('clear_cache_on_exit') is True
    quality=data.get('preview_quality','native')
    result['preview_quality']=quality if quality in ('native','480p','720p','1080p','4k') else 'native'
    result['scrub_audio']=data.get('scrub_audio',True) is not False
    result['tooltips']=data.get('tooltips',True) is not False
    result['auto_update_check']=data.get('auto_update_check',True) is not False
    result['update_previews']=data.get('update_previews',False) is True
    result['video_renderer']=preferred_renderer(data)
    ram=data.get('ram_cache_mb',default_cache_mb())
    result['ram_cache_mb']=max(64,min(maximum_cache_mb(),ram)) if type(ram) is int else default_cache_mb()
    return result

def preference_path():
    return Path(os.environ['CADENCE_PREFS']) if os.environ.get('CADENCE_PREFS') else config_directory()/'preferences.json'

def load_preferences(registry):
    try: return validate(json.loads(preference_path().read_text(encoding='utf-8')),registry)
    except (OSError,ValueError,TypeError): return defaults(registry)

def write_file(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(path)

def save_preferences(data): write_file(preference_path(),data)

class CacheProbe(QObject):
    ready=Signal(int,float)

class ShortcutDialog(QDialog):
    shortcutsChanged=Signal(dict)
    def __init__(self,registry,current,parent=None):
        super().__init__(parent); self.live_data=dict(current,shortcuts=dict(current['shortcuts'])); self.populating=False; self.registry=registry; self.result_data=None; self.setWindowTitle(tr('Options')); self.resize(950,650)
        root=QVBoxLayout(self); tabs=QTabWidget(); root.addWidget(tabs)
        self.tabs=tabs; prefs=QWidget(); general=QVBoxLayout(prefs); general.setContentsMargins(24,20,24,20); general.setSpacing(20)
        def section(title):
            group=QGroupBox(tr(title)); group.setStyleSheet('QGroupBox {border:1px solid #354254;border-radius:7px;margin-top:10px;padding:16px;} QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 6px;}')
            return group
        display=section('Affichage et lecture'); grid=QGridLayout(display); grid.setHorizontalSpacing(20); grid.setVerticalSpacing(14); grid.setColumnStretch(1,1); general.addWidget(display)
        self.language=QComboBox(); self.language.addItem(tr('Français'),'fr'); self.language.addItem(tr('English'),'en')
        self.video_renderer=QComboBox()
        if WINDOWS: self.video_renderer.addItem(tr('Accéléré - Direct3D 11 (recommandé)'),'direct3d')
        self.video_renderer.addItem(tr('Accéléré - OpenGL'),'opengl'); self.video_renderer.addItem(tr('Compatible - logiciel'),'software')
        self.preview_quality=QComboBox()
        for title,value in [('Résolution native','native'),('480p','480p'),('720p','720p'),('1080p','1080p'),('4K','4k')]: self.preview_quality.addItem(tr(title),value)
        self.preview_quality.setEnabled(not bool(getattr(parent,'job',None)))
        for row,(title,control) in enumerate([('Langue',self.language),('Affichage vidéo',self.video_renderer),('Résolution de l’aperçu',self.preview_quality)]):
            grid.addWidget(QLabel(tr(title)),row,0); grid.addWidget(control,row,1)
        note=QLabel(tr('Les changements de langue et d’affichage vidéo prennent effet au prochain démarrage.')); note.setWordWrap(True); note.setStyleSheet('color:#8895a7;'); grid.addWidget(note,3,0,1,2)
        self.scrub_audio=QCheckBox(tr('Son pendant le défilement et le pas-à-pas')); grid.addWidget(self.scrub_audio,4,0,1,2)
        maintenance=QHBoxLayout(); maintenance.setSpacing(20); general.addLayout(maintenance)
        cache=section('Cache'); cache_col=QVBoxLayout(cache); cache_col.setSpacing(14); maintenance.addWidget(cache,1)
        from widgets import ScrubSpinBox
        ram_row=QHBoxLayout(); ram_row.addWidget(QLabel(tr('Cache RAM (Mo)')))
        self.ram_cache=ScrubSpinBox(); self.ram_cache.setRange(64,maximum_cache_mb()); self.ram_cache.setSingleStep(128); ram_row.addWidget(self.ram_cache); cache_col.addLayout(ram_row)
        self.clear_on_exit=QCheckBox(tr('Vider le cache à la fermeture')); cache_col.addWidget(self.clear_on_exit)
        self.cache_label=QLabel(tr('Cache : calcul en cours…')); self.cache_label.setStyleSheet('color:#8895a7;'); cache_col.addWidget(self.cache_label)
        self.clear_button=QPushButton(tr('Vider le cache maintenant')); self.clear_button.clicked.connect(self.clear_cache); self.clear_button.setEnabled(not bool(getattr(parent,'job',None))); cache_col.addWidget(self.clear_button,0,Qt.AlignmentFlag.AlignLeft)
        interface=section('Interface'); interface_col=QVBoxLayout(interface); maintenance.addWidget(interface,1)
        self.tooltips=QCheckBox(tr('Afficher les infobulles')); interface_col.addWidget(self.tooltips)
        restore=QPushButton(tr('Restaurer l’interface')); restore.setEnabled(hasattr(parent,'workspaces')); restore.clicked.connect(lambda:parent.workspaces.reset(True)); interface_col.addWidget(restore,0,Qt.AlignmentFlag.AlignLeft); interface_col.addStretch()
        updates=section('Mises à jour'); updates_col=QVBoxLayout(updates); general.addWidget(updates)
        self.auto_update_check=QCheckBox(tr('Vérifier automatiquement les mises à jour')); updates_col.addWidget(self.auto_update_check)
        self.update_previews=QCheckBox(tr('Proposer les versions de test')); updates_col.addWidget(self.update_previews)
        general.addStretch(); tabs.addTab(prefs,tr('Préférences')); self.cache_probe=CacheProbe(self); self.cache_probe.ready.connect(self.cache_ready); self.cache_generation=0
        QTimer.singleShot(0,self.update_cache_label)
        keys=QWidget(); self.keys_layout=QVBoxLayout(keys); tabs.addTab(keys,tr('Raccourcis'))
        self._editors={}; self._key_values={}; self.keys_ready=False; tabs.currentChanged.connect(lambda index:self.ensure_keys() if index==1 else None)
        gestures=QWidget(); gl=QVBoxLayout(gestures)
        self.gestures={}; table=QTableWidget(3,6); table.setHorizontalHeaderLabels(tr(['Geste','Avec clic molette','Axe','Inverser G/D','Inverser H/B',''])); table.verticalHeader().hide(); table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); gl.addWidget(table)
        for row,(name,title) in enumerate([('zoom','Zoom'),('rotate','Rotation'),('pan','Translation')]):
            item=QTableWidgetItem(tr(title)); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable); table.setItem(row,0,item)
            modifier=QComboBox(); modifier.addItems(tr(MODIFIERS)); axis=QComboBox(); axis.addItem(tr('Horizontal'),'x'); axis.addItem(tr('Vertical'),'y'); axis.setEnabled(name!='pan'); axis.setToolTip(tr('La translation utilise les deux axes.'))
            invx=QCheckBox(); invy=QCheckBox(); self.gestures[name]=(modifier,axis,invx,invy)
            for col,widget in enumerate((modifier,axis,invx,invy),1): table.setCellWidget(row,col,widget)
            reset=QPushButton(tr('Réinitialiser')); reset.clicked.connect(lambda checked=False,n=name:self.reset_gesture(n)); table.setCellWidget(row,5,reset); table.setRowHeight(row,45)
        from widgets import ScrubDoubleSpinBox
        row=QHBoxLayout(); row.addWidget(QLabel(tr('Scrub vidéo : pixels par image'))); self.scrub=ScrubDoubleSpinBox(); self.scrub.setRange(.25,100); self.scrub.setSingleStep(.5); row.addWidget(self.scrub)
        reset=QPushButton(tr('Réinitialiser')); reset.clicked.connect(self.reset_scrub); row.addWidget(reset); gl.addLayout(row); tabs.addTab(gestures,tr('Vue et navigation'))
        exchanges=QWidget(); row=QHBoxLayout(exchanges); row.setContentsMargins(0,0,0,0)
        for title,fn in [('Importer…',self.import_file),('Exporter…',self.export_file),('Tout réinitialiser…',self.reset_all)]:
            b=QPushButton(tr(title)); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); root.addWidget(exchanges); exchanges.hide(); tabs.currentChanged.connect(lambda index:exchanges.setVisible(index>0))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Close); buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr('Enregistrer')); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Annuler')); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        from dialogs import ButtonStyle
        self.button_style=ButtonStyle('Fusion'); self.button_style.setParent(self); buttons.setCenterButtons(True)
        for standard,title in [(QDialogButtonBox.StandardButton.Save,tr('Enregistrer')),(QDialogButtonBox.StandardButton.Cancel,tr('Annuler'))]:
            button=buttons.button(standard); button.setText('&'+title); button.setStyle(self.button_style)
        close=buttons.button(QDialogButtonBox.StandardButton.Close); close.setText('&'+tr('Fermer')); close.setStyle(self.button_style); close.hide()
        self.dialog_buttons=buttons.buttons()
        def show_buttons(index):
            buttons.button(QDialogButtonBox.StandardButton.Save).setVisible(index==0)
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setVisible(index==0)
            close.setVisible(index!=0)
        tabs.currentChanged.connect(show_buttons)
        self.populate(current)
        self.live_ready=True
        for name,(modifier,axis,invx,invy) in self.gestures.items():
            modifier.currentIndexChanged.connect(lambda index,n=name:self.gesture_changed(n))
            axis.currentIndexChanged.connect(self.save_navigation)
            invx.toggled.connect(self.save_navigation); invy.toggled.connect(self.save_navigation)
        self.scrub.valueChanged.connect(self.save_navigation)
        buttons.button(QDialogButtonBox.StandardButton.Save).setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Save).setFocus(Qt.FocusReason.OtherFocusReason)
    def keyPressEvent(self,event):
        if self.focusWidget() in self.dialog_buttons and event.modifiers()==Qt.KeyboardModifier.NoModifier and not event.isAutoRepeat():
            for button in self.dialog_buttons:
                if button.isVisible() and event.text().casefold()==button.text().replace('&','')[0].casefold():
                    button.click(); event.accept(); return
        super().keyPressEvent(event)
    @property
    def editors(self):
        self.ensure_keys(); return self._editors
    def ensure_keys(self):
        if self.keys_ready: return
        self.keys_ready=True
        from menu_layout import alphabetical
        from shortcut_edit import ShortcutEdit
        self.key_tabs=QTabWidget(); self.keys_layout.addWidget(self.key_tabs); self.key_tables={}
        self._editors={}
        for category in dict.fromkeys(key.split('/',1)[0] for key in self.registry):
            keys=sorted((key for key in self.registry if key.split('/',1)[0]==category),key=lambda key:alphabetical(self.registry[key][0].text()))
            table=QTableWidget(len(keys),4); self.key_tables[category]=table; self.key_tabs.addTab(table,tr(category))
            table.setHorizontalHeaderLabels(tr(['Commande','Raccourci','',''])); table.verticalHeader().hide()
            table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(1,200); table.setColumnWidth(2,100); table.setColumnWidth(3,120)
            for row,key in enumerate(keys):
                item=QTableWidgetItem(self.registry[key][0].text().replace('&','')); item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable); table.setItem(row,0,item)
                edit=ShortcutEdit(); self._editors[key]=edit; table.setCellWidget(row,1,edit)
                reset=QPushButton('&'+tr('Réinitialiser')); reset.clicked.connect(lambda checked=False,k=key:self.reset_key(k)); table.setCellWidget(row,3,reset); table.setRowHeight(row,42)
                clear=QPushButton('&'+tr('Effacer')); clear.clicked.connect(lambda checked=False,k=key:self.set_key(k,'')); table.setCellWidget(row,2,clear)
        self.table=next(iter(self.key_tables.values()))
        for key,edit in self._editors.items():
            edit.setKeySequence(QKeySequence(self._key_values.get(key,self.registry[key][1])))
            edit.setClearButtonEnabled(False)
            edit.editingFinished.connect(lambda k=key:self.key_finished(k))
    def show_key(self,key):
        self.ensure_keys(); self.tabs.setCurrentIndex(1)
        self.key_tabs.setCurrentWidget(self.key_tables[key.split('/',1)[0]])
        self.editors[key].setFocus()
    def populate(self,data):
        self.populating=True
        self.ram_cache.setValue(data.get('ram_cache_mb',default_cache_mb()))
        self.video_renderer.setCurrentIndex(self.video_renderer.findData(preferred_renderer(data)))
        self.language.setCurrentIndex(self.language.findData(data.get('language','fr'))); self.clear_on_exit.setChecked(data.get('clear_cache_on_exit',False))
        self.preview_quality.setCurrentIndex(self.preview_quality.findData(data.get('preview_quality','native'))); self.scrub_audio.setChecked(data.get('scrub_audio',True))
        self.tooltips.setChecked(data.get('tooltips',True))
        self.auto_update_check.setChecked(data.get('auto_update_check',True)); self.update_previews.setChecked(data.get('update_previews',False))
        self._key_values=dict(data['shortcuts'])
        for key,edit in self._editors.items(): edit.setKeySequence(QKeySequence(data['shortcuts'].get(key,self.registry[key][1])))
        for name,config in data['canvas'].items(): self.populate_gesture(name,config)
        self.scrub.setValue(data['scrub_pixels'])
        self.populating=False
        if getattr(self,'live_ready',False): self.save_navigation(include_keys=True)
    def populate_gesture(self,name,config):
        modifier,axis,invx,invy=self.gestures[name]; modifier.setCurrentIndex(MODIFIERS.index(config['modifiers'])); axis.setCurrentIndex(axis.findData(config['axis'])); invx.setChecked(config['invert_x']); invy.setChecked(config['invert_y'])
    def collect(self):
        data=defaults(self.registry); data['shortcuts']={key:edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText) for key,edit in self._editors.items()} if self.keys_ready else dict(self._key_values)
        data['canvas']={name:dict(modifiers=MODIFIERS[mod.currentIndex()],axis=axis.currentData(),invert_x=x.isChecked(),invert_y=y.isChecked()) for name,(mod,axis,x,y) in self.gestures.items()}; data['scrub_pixels']=self.scrub.value()
        data['language']=self.language.currentData(); data['clear_cache_on_exit']=self.clear_on_exit.isChecked()
        data['preview_quality']=self.preview_quality.currentData(); data['scrub_audio']=self.scrub_audio.isChecked()
        data['tooltips']=self.tooltips.isChecked()
        data['auto_update_check']=self.auto_update_check.isChecked(); data['update_previews']=self.update_previews.isChecked()
        data['video_renderer']=self.video_renderer.currentData()
        data['ram_cache_mb']=self.ram_cache.value()
        return validate(data,self.registry)
    def gesture_changed(self,name):
        if self.populating: return
        value=MODIFIERS[self.gestures[name][0].currentIndex()]
        previous=self.live_data['canvas'][name]['modifiers']
        for other,(modifier,*_) in self.gestures.items():
            if other!=name and MODIFIERS[modifier.currentIndex()]==value:
                with QSignalBlocker(modifier): modifier.setCurrentIndex(MODIFIERS.index(previous))
        self.save_navigation()
    def save_navigation(self,*args,include_keys=False):
        if self.populating: return
        data=dict(self.live_data)
        data['canvas']={name:dict(modifiers=MODIFIERS[mod.currentIndex()],axis=axis.currentData(),invert_x=x.isChecked(),invert_y=y.isChecked()) for name,(mod,axis,x,y) in self.gestures.items()}
        data['scrub_pixels']=self.scrub.value()
        if include_keys: data['shortcuts']=dict(self._key_values)
        try: data=validate(data,self.registry); save_preferences(data)
        except (ValueError,OSError) as error:
            QMessageBox.warning(self,tr('Enregistrement impossible'),tr(str(error))); return
        self.live_data=data; self.shortcutsChanged.emit(data)
    def set_key(self,key,value):
        self.editors[key].setKeySequence(QKeySequence(value)); self.key_finished(key)
    def key_finished(self,key):
        if self.populating or getattr(self,'_resolving_shortcut',False): return
        value=self.editors[key].keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        previous=self.live_data['shortcuts'].get(key,'')
        if value==previous: return
        sequence=QKeySequence(value,QKeySequence.SequenceFormat.PortableText)
        conflicts=[]
        if value:
            for other,saved in self.live_data['shortcuts'].items():
                if other==key or not saved: continue
                candidate=QKeySequence(saved,QKeySequence.SequenceFormat.PortableText)
                if sequence.matches(candidate)!=QKeySequence.SequenceMatch.NoMatch or candidate.matches(sequence)!=QKeySequence.SequenceMatch.NoMatch: conflicts.append(other)
        if conflicts:
            from shortcut_edit import ConflictDialog
            self._resolving_shortcut=True
            try:
                box=ConflictDialog(self,conflicts)
                accepted=box.exec()==QDialog.DialogCode.Accepted
                if not accepted:
                    with QSignalBlocker(self.editors[key]): self.editors[key].setKeySequence(QKeySequence(previous))
                    return
            finally: self._resolving_shortcut=False
        updated=dict(self.live_data,shortcuts=dict(self.live_data['shortcuts']))
        updated['shortcuts'][key]=value
        for other in conflicts: updated['shortcuts'][other]=''
        try: updated=validate(updated,self.registry); save_preferences(updated)
        except (ValueError,OSError) as error:
            with QSignalBlocker(self.editors[key]): self.editors[key].setKeySequence(QKeySequence(previous))
            QMessageBox.warning(self,tr('Raccourcis invalides'),tr(str(error))); return
        self.live_data=updated; self._key_values=dict(updated['shortcuts'])
        for other in conflicts:
            with QSignalBlocker(self.editors[other]): self.editors[other].clear()
        self.shortcutsChanged.emit(updated)
    def update_cache_label(self):
        import threading
        self.cache_generation+=1; generation=self.cache_generation; probe=self.cache_probe
        def measure():
            from cache_tools import cache_bytes
            size=cache_bytes()
            try: probe.ready.emit(generation,float(size))
            except RuntimeError: pass # Closed/deleted dialog.
        threading.Thread(target=measure,daemon=True).start()
    def cache_ready(self,generation,size):
        if generation==self.cache_generation: self.cache_label.setText(tr(f'Cache : {size/1024/1024:.1f} Mo'))
    def clear_cache(self):
        from cache_tools import clear_cache
        parent=self.parent(); media=list(getattr(getattr(parent,'doc',None),'media',{}).values())
        media+=list(getattr(parent,'reference_sources',{}).values())
        protected=[m.get(field) for m in media for field in ('proxy','audio')]
        deleted,kept,failed,freed=clear_cache(protected)
        self.update_cache_label()
        QMessageBox.information(self,tr('Cache'),tr(f'{freed/1024/1024:.1f} Mo libérés.\n{kept} médias en cours conservés.\n{failed} dossiers occupés ou inaccessibles.'))
    def confirm_reset(self,message):
        return QMessageBox.warning(self,tr('Réinitialiser les réglages'),tr(message+'\nLes personnalisations concernées seront remplacées. Continuer ?'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
    def reset_key(self,key):
        if self.confirm_reset(tr('Réinitialiser « {command} » ?').format(command=tr(key))): self.set_key(key,self.registry[key][1])
    def reset_gesture(self,name):
        if self.confirm_reset('Réinitialiser ce geste du canvas ?'):
            self.populating=True; self.populate_gesture(name,default_canvas()[name]); self.populating=False; self.gesture_changed(name)
    def reset_scrub(self):
        if self.confirm_reset('Réinitialiser la sensibilité du scrub ?'): self.scrub.setValue(4)
    def reset_all(self):
        if self.confirm_reset('Réinitialiser TOUS les raccourcis, gestes du canvas et réglages du scrub ?'):
            data=defaults(self.registry); data.update(self.general_preferences()); self.populate(data)
    def general_preferences(self):
        return dict(auto_update_check=self.auto_update_check.isChecked(),update_previews=self.update_previews.isChecked(),ram_cache_mb=self.ram_cache.value(),language=self.language.currentData(),clear_cache_on_exit=self.clear_on_exit.isChecked(),preview_quality=self.preview_quality.currentData(),scrub_audio=self.scrub_audio.isChecked(),tooltips=self.tooltips.isChecked(),video_renderer=self.video_renderer.currentData(),video_renderer_version=2)
    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,tr('Importer les raccourcis'),'',tr('Raccourcis Cadence (*.json)'))
        if not path: return
        try:
            if Path(path).stat().st_size>1024*1024: raise ValueError('Fichier trop volumineux.')
            data=validate(json.loads(Path(path).read_text(encoding='utf-8')),self.registry)
            data.update(self.general_preferences())
            self.populate(data)
        except (OSError,ValueError,TypeError) as error: QMessageBox.warning(self,tr('Import impossible'),tr(str(error)))
    def export_file(self):
        try: data=self.collect()
        except ValueError as error: QMessageBox.warning(self,tr('Raccourcis invalides'),tr(str(error))); return
        for key in self.general_preferences(): data.pop(key,None)
        path,_=QFileDialog.getSaveFileName(self,tr('Exporter les raccourcis'),'Cadence-raccourcis.json',tr('Raccourcis Cadence (*.json)'))
        if path:
            try: write_file(path,data)
            except OSError as error: QMessageBox.warning(self,tr('Export impossible'),tr(str(error)))
    def accept(self):
        try:
            data=self.collect(); save_preferences(data); self.result_data=data
        except (OSError,ValueError) as error: QMessageBox.warning(self,tr('Enregistrement impossible'),tr(str(error))); return
        super().accept()
