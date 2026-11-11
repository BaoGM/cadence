# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import tempfile

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog,QLineEdit
from ui_text import tr


FORMATS = {
    '.mp4': 'Vidéo MP4 (*.mp4)',
    '.mov': 'Vidéo MOV (*.mov)',
    '.gif': 'GIF animé (*.gif)',
    '.wav': 'Audio WAV (*.wav)',
    '.mp3': 'Audio MP3 (*.mp3)',
}


def default_destination(doc):
    video = any(s.media in doc.media and not s.muted and doc.media[s.media].get('has_video', True)
                for s in doc.state.segments)
    audio_only = not video and not doc.state.drawings
    extension = '.wav' if audio_only else '.mp4'
    source = next((doc.media[s.media] for s in doc.state.segments + doc.state.audio if s.media in doc.media), None)
    folders = []
    if doc.project_path:
        project = Path(doc.project_path).resolve()
        folders.append(project.parent)
        name = project.stem
    else:
        name = Path(source['path']).stem if source else tr('Montage')
    if source:
        folders.append(Path(source['path']).resolve().parent)
    locations = (QStandardPaths.StandardLocation.MusicLocation if audio_only else QStandardPaths.StandardLocation.MoviesLocation,
                 QStandardPaths.StandardLocation.DocumentsLocation, QStandardPaths.StandardLocation.HomeLocation)
    folders.extend(Path(path) for location in locations if (path := QStandardPaths.writableLocation(location)))
    for folder in dict.fromkeys(folders):
        try:
            with tempfile.TemporaryFile(dir=folder, prefix='.cadence-write-'):
                pass
        except OSError:
            continue
        return folder / (name + '-montage' + extension)
    raise ValueError('Aucun dossier accessible en écriture pour l’export.')


class ExportDialog(QFileDialog):
    def __init__(self, parent, doc):
        destination = default_destination(doc)
        super().__init__(parent, tr('Exporter le montage'), str(destination.parent))
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        self.setFileMode(QFileDialog.FileMode.AnyFile)
        self.formats = {tr(label): extension for extension, label in FORMATS.items()}
        self.setNameFilters(list(self.formats))
        self.selectNameFilter(tr(FORMATS[destination.suffix]))
        self.setDefaultSuffix(destination.suffix[1:])
        self.selectFile(destination.name)
        self.filterSelected.connect(self.change_format)

    def change_format(self, label):
        extension = self.formats[label]
        selected = self.selectedFiles()
        self.setDefaultSuffix(extension[1:])
        editor = self.findChild(QLineEdit,'fileNameEdit')
        if editor is not None and not editor.text().strip(): return
        if selected:
            path = Path(selected[0])
            if path.suffix.lower() in FORMATS:
                path = path.with_suffix(extension)
            elif not path.suffix:
                path = path.with_name(path.name + extension)
            if Path(self.directory().absolutePath()) != path.parent:
                self.setDirectory(str(path.parent))
            self.selectFile(path.name)
            # selectFile leaves the filename editor unchanged while it has focus.
            if editor is not None: editor.setText(path.name)
