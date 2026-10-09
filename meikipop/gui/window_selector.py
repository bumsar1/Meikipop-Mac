"""Choose and verify the source window before starting screenshot mining."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QApplication
from meikipop.screenshot.window_capture import list_windows, capture_window


class WindowSelector(QDialog):
    def __init__(self, current_id=None, parent=None):
        super().__init__(parent)
        self.current_id = current_id
        self.selected_window = None
        self.setWindowTitle('Vælg vindue til Anki-billeder')
        self.resize(650, 570)
        layout = QVBoxLayout(self)
        label = QLabel('Vælg spilvinduet. Valget bruges til kortets billede, også når et andet program har fokus.\nScanningsområdet til ord vælges bagefter som normalt.')
        label.setWordWrap(True);layout.addWidget(label)
        self.windows = QListWidget();layout.addWidget(self.windows)
        self.preview = QLabel('Vælg et vindue og tryk “Brug vindue”.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setMinimumHeight(180)
        layout.addWidget(self.preview)
        self.status = QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status)
        row=QHBoxLayout();layout.addLayout(row)
        refresh=QPushButton('Opdatér liste');refresh.clicked.connect(self.refresh);row.addWidget(refresh)
        row.addStretch()
        cancel=QPushButton('Annuller');cancel.clicked.connect(self.reject);row.addWidget(cancel)
        self.use=QPushButton('Brug vindue');self.use.clicked.connect(self.use_selected);row.addWidget(self.use)
        self.windows.itemSelectionChanged.connect(self.selection_changed)
        self.refresh()

    def refresh(self):
        self.windows.clear();self.selected_window=None;self.preview.clear()
        try:
            for window in list_windows():
                b=window['bounds']
                name=window['app'] + (' — '+window['title'] if window['title'] else '')
                item=QListWidgetItem(f"{name}  ({int(b['Width'])} × {int(b['Height'])})")
                item.setData(Qt.ItemDataRole.UserRole,window);self.windows.addItem(item)
                if window['id']==self.current_id:self.windows.setCurrentItem(item)
            self.status.setText('' if self.windows.count() else 'Ingen vinduer fundet. Åbn spillet, og tryk Opdatér liste.')
        except Exception as e:
            self.status.setText(str(e))
        self.selection_changed()

    def selection_changed(self):
        self.use.setEnabled(self.windows.currentItem() is not None)
        self.selected_window=None
        self.use.setText('Brug vindue')

    def use_selected(self):
        if self.selected_window is not None:
            self.accept();return
        item=self.windows.currentItem()
        if item is None:return
        window=item.data(Qt.ItemDataRole.UserRole)
        self.status.setText('Kontrollerer vinduesbilledet…');QApplication.processEvents()
        try:
            frame=capture_window(window['id'],window['pid'])
            pixmap=QPixmap()
            if not pixmap.loadFromData(frame.png,'PNG'):
                raise RuntimeError('Vinduesbilledet kunne ikke læses.')
            self.preview.setPixmap(pixmap.scaled(600,230,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            self.selected_window=window
            self.status.setText('Billedet er hentet. Tryk Fortsæt, hvis det er det rigtige vindue.')
            self.use.setText('Fortsæt')
        except Exception as e:
            self.status.setText('Billedtagningen fejlede: '+str(e))

    @classmethod
    def choose(cls,current_id=None):
        dialog=cls(current_id)
        return dialog.selected_window if dialog.exec()==QDialog.DialogCode.Accepted else None
