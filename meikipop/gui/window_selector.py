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
        self.setWindowTitle('Select Window for Anki Screenshots')
        self.resize(650, 570)
        layout = QVBoxLayout(self)
        label = QLabel('Select the game window. It will provide card screenshots even when another app has focus.\nYou will select the text scanning region next.')
        label.setWordWrap(True);layout.addWidget(label)
        self.windows = QListWidget();layout.addWidget(self.windows)
        self.preview = QLabel('Select a window and click “Use Window”.')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setMinimumHeight(180)
        layout.addWidget(self.preview)
        self.status = QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status)
        row=QHBoxLayout();layout.addLayout(row)
        refresh=QPushButton('Refresh List');refresh.clicked.connect(self.refresh);row.addWidget(refresh)
        row.addStretch()
        cancel=QPushButton('Cancel');cancel.clicked.connect(self.reject);row.addWidget(cancel)
        self.use=QPushButton('Use Window');self.use.clicked.connect(self.use_selected);row.addWidget(self.use)
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
            self.status.setText('' if self.windows.count() else 'No windows found. Open your game and click Refresh List.')
        except Exception as e:
            self.status.setText(str(e))
        self.selection_changed()

    def selection_changed(self):
        self.use.setEnabled(self.windows.currentItem() is not None)
        self.selected_window=None
        self.use.setText('Use Window')

    def use_selected(self):
        if self.selected_window is not None:
            self.accept();return
        item=self.windows.currentItem()
        if item is None:return
        window=item.data(Qt.ItemDataRole.UserRole)
        self.status.setText('Checking window screenshot…');QApplication.processEvents()
        try:
            frame=capture_window(window['id'],window['pid'])
            pixmap=QPixmap()
            if not pixmap.loadFromData(frame.png,'PNG'):
                raise RuntimeError('Could not read the window screenshot.')
            self.preview.setPixmap(pixmap.scaled(600,230,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            self.selected_window=window
            self.status.setText('Screenshot captured. Click Continue if this is the correct window.')
            self.use.setText('Continue')
        except Exception as e:
            self.status.setText('Screenshot capture failed: '+str(e))

    @classmethod
    def choose(cls,current_id=None):
        dialog=cls(current_id)
        return dialog.selected_window if dialog.exec()==QDialog.DialogCode.Accepted else None
