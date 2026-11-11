# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject,QEvent,QStandardPaths,QUrl,Qt,QSize,Slot
from PySide6.QtGui import QPixmap,QIcon,QPainter,QPainterPath,QColor
from PySide6.QtWidgets import QApplication,QFileDialog,QToolButton,QListView,QFileIconProvider
from ui_text import tr

def navigation_icon(direction):
    icon=QIcon()
    points={'left':[(16,5),(7,12),(16,19)],'right':[(8,5),(17,12),(8,19)],'up':[(5,16),(12,7),(19,16)]}[direction]
    for scale in (1,2,3):
        for mode,color in ((QIcon.Mode.Normal,'#cbd7e4'),(QIcon.Mode.Active,'#e8edf5'),(QIcon.Mode.Disabled,'#697889')):
            pixmap=QPixmap(24*scale,24*scale); pixmap.fill(Qt.GlobalColor.transparent)
            p=QPainter(pixmap); p.scale(scale,scale); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            path=QPainterPath(); path.moveTo(*points[0])
            for point in points[1:]: path.lineTo(*point)
            path.closeSubpath(); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color)); p.drawPath(path); p.end()
            pixmap.setDevicePixelRatio(scale); icon.addPixmap(pixmap,mode)
    return icon

class LocalizedFileIcons(QFileIconProvider):
    def type(self,info):
        if info.isDir(): return tr('Dossier')
        if info.isFile(): return tr('Fichier {extension}').format(extension=info.suffix().upper()).strip()
        return super().type(info)


class SidebarLabels(QObject):
    def __init__(self,sidebar):
        super().__init__(sidebar)
        self.model=sidebar.model()
        self.desktop=QUrl.fromLocalFile(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation))
        for signal in (self.model.dataChanged,self.model.rowsInserted,self.model.modelReset):
            signal.connect(self.refresh)
        self.refresh()

    @Slot()
    def refresh(self):
        for row in range(self.model.rowCount()):
            index=self.model.index(row,0)
            if index.data(Qt.ItemDataRole.UserRole+1)==self.desktop and index.data()!=tr('Bureau'):
                self.model.setData(index,tr('Bureau'),Qt.ItemDataRole.DisplayRole)


class FilePlaces(QObject):

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Show and isinstance(obj,QFileDialog):
            filename='Nom de dossier :' if obj.fileMode()==QFileDialog.FileMode.Directory else 'Nom de fichier :'
            for role,text in ((QFileDialog.DialogLabel.LookIn,'Dossier :'),
                              (QFileDialog.DialogLabel.FileName,filename),
                              (QFileDialog.DialogLabel.FileType,'Type de fichier :')):
                obj.setLabelText(role,tr(text))
            desktop=QUrl.fromLocalFile(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation))
            places=obj.sidebarUrls()
            if desktop not in places: obj.setSidebarUrls([desktop]+places)
            sidebar=obj.findChild(QListView,'sidebar')
            if sidebar:
                if not hasattr(sidebar,'cadence_labels'):
                    sidebar.cadence_labels=SidebarLabels(sidebar)
                sidebar.cadence_labels.refresh()
            if not hasattr(obj,'cadence_file_icons'):
                obj.cadence_file_icons=LocalizedFileIcons()
                obj.setIconProvider(obj.cadence_file_icons)
            if not hasattr(self,'arrows'): self.arrows={direction:navigation_icon(direction) for direction in ('left','right','up')}
            for name,direction in [('backButton','left'),('forwardButton','right'),('toParentButton','up')]:
                button=obj.findChild(QToolButton,name)
                if button: button.setIcon(self.arrows[direction]); button.setIconSize(QSize(24,24))
        return False

def install_file_places():
    app=QApplication.instance()
    if hasattr(app,'cadence_file_places'): return
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs,True)
    app.cadence_file_places=FilePlaces(app)
    app.installEventFilter(app.cadence_file_places)
