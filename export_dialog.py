# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import tempfile

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QCheckBox,QFileDialog,QHBoxLayout,QLabel,QLineEdit,QSpinBox,QWidget
from studio_export import PROFILES, sequence_folder
from library_style import ElideLabel
from ui_text import tr


FORMATS = {
    '.mp4': 'Vidéo MP4 (*.mp4)',
    '.mov': 'MOV H.264 (*.mov)',
    '.gif': 'GIF animé (*.gif)',
    '.wav': 'Audio WAV (*.wav)',
    '.mp3': 'Audio MP3 (*.mp3)',
}


def default_destination(doc):
    video = any(s.media in doc.media and not s.muted and doc.media[s.media].get('has_video', True)
                for track in doc.state.tracks for s in track.segments)
    audio_only = not video and not doc.state.drawings
    extension = '.wav' if audio_only else '.mp4'
    source = next((doc.media[s.media] for s in doc.state.all_segments if s.media in doc.media), None)
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
        self.setOption(QFileDialog.Option.DontUseNativeDialog)
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        self.setFileMode(QFileDialog.FileMode.AnyFile)
        self.formats = {tr(label): extension for extension, label in FORMATS.items()}
        self.profiles = {tr(fmt.label): key for key, fmt in PROFILES.items()}
        self.length = doc.state.length
        self.formats.update({label: PROFILES[key].extension for label, key in self.profiles.items()})
        self.setNameFilters(list(self.formats))
        self.selectNameFilter(tr(FORMATS[destination.suffix]))
        self.setDefaultSuffix(destination.suffix[1:])
        self.selectFile(destination.name)
        self.studio_controls = QWidget(self)
        row = QHBoxLayout(self.studio_controls)
        row.setContentsMargins(0,0,0,0)
        self.number_label = QLabel(tr('Première image'))
        self.first_frame = QSpinBox()
        self.first_frame.setRange(0,99_999_999)
        self.first_frame.setValue(1001)
        self.number_label.setBuddy(self.first_frame)
        self.drawings_only = QCheckBox(tr('Dessins seuls'))
        self.sequence_label = ElideLabel()
        row.addWidget(self.number_label)
        row.addWidget(self.first_frame)
        row.addWidget(self.drawings_only)
        row.addStretch()
        layout = self.layout()
        layout.addWidget(self.studio_controls,layout.rowCount(),0,1,layout.columnCount())
        layout.addWidget(self.sequence_label,layout.rowCount(),0,1,layout.columnCount())
        editor = self.findChild(QLineEdit,'fileNameEdit')
        editor.textChanged.connect(self.update_sequence_label)
        self.first_frame.valueChanged.connect(self.update_sequence_label)
        self.update_controls()
        self.filterSelected.connect(self.change_format)

    def update_sequence_label(self,*_):
        fmt = PROFILES.get(self.profiles.get(self.selectedNameFilter()))
        editor = self.findChild(QLineEdit,'fileNameEdit')
        if fmt and fmt.sequence and editor.text().strip():
            base = Path(editor.text().strip()).name
            if base in ('.','..',''): return
            path = Path(base).with_suffix(fmt.extension)
            number = self.first_frame.value()
            digits = max(4,len(str(number+self.length-1)))
            example = f'{sequence_folder(path).name}/{path.stem}.{number:0{digits}d}{fmt.extension}'
            self.sequence_label.setText(tr('Séquence') + ' · ' + example)
            self.sequence_label.setToolTip(example)
        else: self.sequence_label.clear()

    def update_controls(self):
        fmt = PROFILES.get(self.profiles.get(self.selectedNameFilter()))
        self.studio_controls.setVisible(bool(fmt and (fmt.sequence or fmt.alpha)))
        self.first_frame.setVisible(bool(fmt and fmt.sequence))
        self.number_label.setVisible(bool(fmt and fmt.sequence))
        self.drawings_only.setVisible(bool(fmt and fmt.alpha))
        self.sequence_label.setVisible(bool(fmt and fmt.sequence))
        self.update_sequence_label()

    def render_options(self):
        profile = self.profiles.get(self.selectedNameFilter())
        if not profile: return {}
        return dict(profile=profile,first_frame=self.first_frame.value(),
                    drawings_only=PROFILES[profile].alpha and self.drawings_only.isChecked())

    def change_format(self, label):
        extension = self.formats[label]
        self.update_controls()
        selected = self.selectedFiles()
        self.setDefaultSuffix(extension[1:])
        editor = self.findChild(QLineEdit,'fileNameEdit')
        if editor is not None and not editor.text().strip(): return
        if selected:
            path = Path(selected[0])
            if path.suffix.lower() in self.formats.values():
                path = path.with_suffix(extension)
            elif not path.suffix:
                path = path.with_name(path.name + extension)
            if Path(self.directory().absolutePath()) != path.parent:
                self.setDirectory(str(path.parent))
            self.selectFile(path.name)
            # selectFile leaves the filename editor unchanged while it has focus.
            if editor is not None: editor.setText(path.name)
