# SPDX-License-Identifier: GPL-3.0-only
from ui_text import tr,source
import unicodedata
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtWidgets import (QApplication,QWidget,QFrame,QLabel,QDockWidget,QToolBar,QStatusBar,QMenu,QDialog,
    QAbstractButton,QAbstractItemView,QAbstractSlider,QAbstractSpinBox,QLineEdit,QMenuBar,QTabBar)

def alphabetical(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))

GROUPS={
    'Fichier':[
        ['Nouveau montage','Ouvrir des vidéos…','Ouvrir un projet…'],
        ['Enregistrer','Enregistrer sous…','Exporter…'],
        ['Capturer l’écran…','Démarrer / arrêter la capture'],
        ['Associer les vidéos et projets à cette version','Dossier du cache'],
        ['Options…'],['Quitter']],
    'Édition':[
        ['Annuler','Rétablir'],
        ['Coller les images','Copier les images','Couper les images','Supprimer les images'],
        ['Effacer la sélection / quitter le plein écran','Tout sélectionner']],
    'Lecture':[
        ['Lecture / pause'],
        ['Début','Fin','Image précédente','Image suivante'],
        ['Clé précédente','Clé suivante']],
    'Affichage':[
        ['Afficher la timeline','Afficher le bandeau supérieur',
         'Afficher les commandes de lecture','Afficher le time code','Afficher la liste de lecture','Afficher la barre d’outils','Afficher les outils de dessin','Afficher les réglages de comparaison'],
        # Preserve the requested usage order: zoom/reset, fullscreen, mirrors, units.
        ['Réinitialiser le canvas','Zoom vidéo +','Zoom vidéo −','Plein écran vidéo','Flip - miroir vertical','Flop - miroir horizontal','Timecode / frames'],
        ['Mode Lecture / Édition','Options des modes Lecture / Édition…'],
        ['Modifier la disposition des panneaux'],
        ['Réinitialiser la disposition des panneaux']],
    'Comparaison':[
        ['Activer la comparaison','Ajouter des références B…'],
        ['Côte à côte','Dessus / dessous','Overlay - transparence','Différence - négatif','A devant B - bascule','Révélateur'],
        ['Intervertir A / B']],
    'Dessin':[
        ['Afficher le calque de dessins'],
        ['Ajouter un marqueur','Dupliquer la clé au curseur'],
        ['Coller les clés','Copier les clés','Couper les clés'],
        ['Supprimer les clés','Supprimer les marqueurs']],
    'Outils':[
        ['Curseur'],
        ['Pinceau','Pipette','Gomme','Lasso / déplacement','Texte','Flèche','Carré','Cercle'],
        ['Recadrer le clip','Transformer la sélection ou le clip','Réinitialiser le cadrage du clip']],
    'Aide':[['Guide rapide','Dossier des journaux'],['À propos']],
}

def organize_menus(window):
    for entry in window.menuBar().actions():
        menu=entry.menu()
        if menu is None: continue
        original=menu.actions(); remaining={a.property('sourceText') or source(a.text()):a for a in original if not a.isSeparator()}
        groups=[]
        for index,titles in enumerate(GROUPS.get(source(menu.title()),[])):
            group=[remaining.pop(title) for title in titles if title in remaining]
            if (source(menu.title()),index) not in (('Affichage',1),('Outils',2)): group.sort(key=lambda a:alphabetical(a.text()))
            if group: groups.append(group)
        # Keep future commands visible even before their usage group is specified.
        if remaining: groups.append(sorted(remaining.values(),key=lambda a:alphabetical(a.text())))
        for action in original:
            menu.removeAction(action)
            if action.isSeparator(): action.deleteLater()
        for index,group in enumerate(groups):
            if index: menu.addSeparator()
            for action in group: menu.addAction(tr(action))

PANEL_NAMES={
    'timeline':'Timeline','header':'Bandeau supérieur',
    'transport':'Commandes de lecture','timecode':'Time code',
    'comparison':'Comparaison','drawing':'Dessin','tools':'Barre d’outils','library':'Liste de lecture',
}

def panel_menu(window):
    menu=QMenu(tr(window)); menu.setObjectName('panelVisibilityMenu')
    mode=menu.addAction(tr('Mode édition')); mode.setData('workspace_mode'); mode.setCheckable(True)
    mode.setChecked(window.workspaces.mode=='edit')
    mode.triggered.connect(lambda checked:window.workspaces.switch('edit' if checked else 'read'))
    menu.addSeparator()
    commands={**window.panel_actions,'library':window.library_action}
    def trigger(command):
        if window.video_fullscreen: window.toggle_fullscreen()
        command.trigger()
    for key in sorted(commands,key=lambda k:alphabetical(PANEL_NAMES[k])):
        command=commands[key]; action=menu.addAction(tr(PANEL_NAMES[key])); action.setData(key)
        action.setCheckable(True); action.setChecked(command.isChecked()); action.setEnabled(command.isEnabled())
        action.triggered.connect(lambda checked=False,a=command:trigger(a))
    menu.addSeparator()
    timeline=window.timeline
    timeline.add_timeline_mode(menu); menu.addSeparator(); timeline.add_units(menu)
    timeline.add_delete_keys(menu,timeline.x_for(window.doc.state.position+.5))
    menu.addSeparator()
    action=menu.addAction(tr(window.layout_action.text())); action.setCheckable(True); action.setChecked(window.layout_editable)
    action.triggered.connect(lambda:trigger(window.layout_action))
    menu.addSeparator(); menu.addAction(tr(window.reset_layout_action))
    return menu

class BackgroundPanelMenu(QObject):
    def __init__(self,window):
        super().__init__(window); self.window=window
        QApplication.instance().installEventFilter(self)
    def belongs(self,widget):
        # QWidget.isAncestorOf stops at floating windows; ownership does not.
        while widget is not None:
            if widget is self.window: return True
            widget=widget.parentWidget()
        return False
    def eventFilter(self,obj,event):
        if event.type()!=QEvent.Type.ContextMenu or not isinstance(obj,QWidget): return False
        w=self.window
        if not self.belongs(obj): return False
        plain=(QWidget,QFrame,QLabel,QDockWidget,QToolBar,QStatusBar)
        if type(obj) not in plain and obj not in (w,w.viewer): return False
        # Use the original hit widget even when Qt propagates an ignored context event.
        target=(QApplication.widgetAt(event.globalPos()) if event.reason()==event.Reason.Mouse else QApplication.focusWidget()) or obj
        if not self.belongs(target): return False
        if target.contextMenuPolicy()!=Qt.ContextMenuPolicy.DefaultContextMenu: return False
        if type(target) not in plain and target not in (w,w.viewer): return False
        ancestor=target
        while ancestor is not None and ancestor is not w:
            if isinstance(ancestor,(QAbstractButton,QAbstractItemView,QAbstractSlider,QAbstractSpinBox,QLineEdit,QMenu,QMenuBar,QTabBar,QDialog)):
                return False
            ancestor=ancestor.parentWidget()
        menu=w.drawing.objects_menu(w.viewer.mapFromGlobal(event.globalPos())) if target is w.viewer else None
        if menu is None: menu=w.createPopupMenu()
        if target is w.viewer:
            menu.addSeparator(); action=menu.addAction(tr('Verrouiller la position du code temporel')); action.setData('timecode_lock'); action.setCheckable(True)
            action.setChecked(w.timecode_overlay.locked); action.toggled.connect(w.timecode_overlay.set_locked)
        menu.exec(event.globalPos()); menu.deleteLater(); event.accept(); return True
