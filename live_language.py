# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QCoreApplication, QItemSelectionModel, QLocale, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractButton, QDockWidget, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QTextEdit,
                               QMenu, QTabBar, QToolBar, QWidget)

import ui_text


def retranslate(window, wanted):
    if wanted == ui_text.language():
        return
    # Cadence constructs its widgets in Python. Resolve their displayed strings before
    # changing Qt's translator, which also updates some action-backed buttons itself.
    catalog = ui_text.interface_sources()
    ui_text.set_language(wanted)
    window.setLocale(QLocale())

    def translated(value):
        key = catalog.get(value)
        if not key and ' · ' in value:
            return ' · '.join(translated(part) for part in value.split(' · '))
        return ui_text.tr(key) if key else value

    def relabel(getter, setter):
        old = getter()
        new = translated(old)
        if old != new:
            setter(new)

    actions = {action:path for path,(action,_) in window.action_registry.items()}
    for action in window.findChildren(QAction):
        path = actions.get(action)
        if path and not action.menu():
            title = path.split('/',1)[1]
            action.setText('Undo' if wanted=='en' and path=='Édition/Annuler' else ui_text.tr(title))
        else:
            relabel(action.text,action.setText)
        relabel(action.iconText,action.setIconText)
        relabel(action.toolTip,action.setToolTip)

    panel = window.playlists_panel
    data_labels = (window.studio.project,window.studio.media,window.studio.breadcrumb,panel.folder_label)
    native_names = {'qt_dockwidget_floatbutton':('QDockWidget','Float'),
                    'ScrollLeftButton':('QTabBar','Scroll Left'),
                    'ScrollRightButton':('QTabBar','Scroll Right')}
    for widget in window.findChildren(QWidget):
        if widget.isWindow(): widget.setLocale(window.locale())
        if widget in data_labels:
            continue
        relabel(widget.toolTip,widget.setToolTip)
        relabel(widget.accessibleName,widget.setAccessibleName)
        if name:=native_names.get(widget.objectName()):
            widget.setAccessibleName(QCoreApplication.translate(*name))
        if isinstance(widget,(QLabel,QAbstractButton)):
            relabel(widget.text,widget.setText)
        elif isinstance(widget,(QDockWidget,QToolBar)):
            relabel(widget.windowTitle,widget.setWindowTitle)
        elif isinstance(widget,(QMenu,QGroupBox)):
            relabel(widget.title,widget.setTitle)
        elif isinstance(widget,(QLineEdit,QPlainTextEdit,QTextEdit)):
            relabel(widget.placeholderText,widget.setPlaceholderText)
        elif isinstance(widget,QTabBar):
            for index in range(widget.count()):
                widget.setTabText(index,translated(widget.tabText(index)))
                widget.setTabToolTip(index,translated(widget.tabToolTip(index)))

    # Combo boxes containing paths, references, fonts and user-created names are data.
    window.ref_compare_button.setText(ui_text.tr('Comparer'))
    window.ref_compare_button.setAccessibleName(ui_text.tr('Comparer'))
    from draw_ui import TOOL_SPECS
    for combo in (window.drawing.tool,window.compare_mode):
        with QSignalBlocker(combo):
            for index in range(combo.count()):
                name=ui_text.tr(TOOL_SPECS[index][0]) if combo is window.drawing.tool else translated(combo.itemText(index))
                combo.setItemText(index,name)
    for index in range(panel.tree.topLevelItemCount()):
        item=panel.tree.topLevelItem(index)
        item.setText(0,translated(item.text(0)))
    count=panel.files.count()
    panel.folder_count.setText(f"{count} {ui_text.tr('fichier' if count==1 else 'fichiers')}")
    # Rebuild duration, unit and availability labels, preserving row focus and selection.
    lists=(window.playlist,window.media_list,window.reference_list)
    selections=[([view.row(item) for item in view.selectedItems()],view.currentRow(),
                 view.verticalScrollBar().value()) for view in lists]
    window.library_signature=None
    window.studio.language_button.setText('FR / en' if wanted=='fr' else 'EN / fr')
    window.reference_signature=None
    window.track_ref_signature=None
    window.drawing.list_source=None
    window.drawing.list_signature=None
    window.refresh()
    window.refresh_reference_queue()
    for view,(selected,current,scroll) in zip(lists,selections):
        if current>=0: view.setCurrentRow(current,QItemSelectionModel.SelectionFlag.NoUpdate)
        for row in selected:
            if item:=view.item(row): item.setSelected(True)
        view.verticalScrollBar().setValue(scroll)
    window.volume.refresh()
    window.studio.align_workspace()
    window.update()
