# meikipop/gui/dictionaries_dialog.py
import logging
import threading

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QFileDialog, QMessageBox)

from meikipop.config.config import DICT_PATH
from meikipop.dictionary import user_dicts

logger = logging.getLogger(__name__)


class DictionariesDialog(QDialog):
    finished_work = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, lookup, parent=None):
        super().__init__(parent)
        self.lookup = lookup
        self.setWindowTitle("Dictionaries")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("The built-in dictionary (JMdict) is always used. Extra Yomitan dictionaries "
                                "(.zip) are added on top; their definitions show with the dictionary's name."))
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add Yomitan Dictionary…")
        self.add_button.clicked.connect(self.add)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.finished_work.connect(self._done)
        self.progress.connect(self.status.setText)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for path, title, count in user_dicts.list_user_dicts():
            item = QListWidgetItem(f"{title}  ·  {count:,} entries")
            item.setData(256, path)
            self.list.addItem(item)
        self.remove_button.setEnabled(self.list.count() > 0)

    def _busy(self, busy):
        self.add_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy and self.list.count() > 0)

    def add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose Yomitan Dictionaries", "", "Yomitan dictionary (*.zip)")
        if not files:
            return

        def work():
            errors = []
            for f in files:
                try:
                    user_dicts.import_zip(f, self.progress.emit)
                except Exception as e:
                    logger.exception("Import failed: %s", f)
                    errors.append(str(e))
            return errors
        self._run(work)

    def remove(self):
        item = self.list.currentItem() or self.list.item(0)
        if item is None:
            return
        name = item.text().split("  ·  ")[0]
        if QMessageBox.question(self, "Remove Dictionary", f'Remove "{name}" from Meikipop?') != QMessageBox.StandardButton.Yes:
            return
        path = item.data(256)
        self._run(lambda: user_dicts.remove(path) or [])

    def _run(self, work):
        self._busy(True)

        def job():
            try:
                errors = work()
                self.progress.emit("Reloading dictionaries…")
                from meikipop.dictionary.customdict import Dictionary
                fresh = Dictionary()
                if not fresh.load_dictionary(DICT_PATH):
                    raise RuntimeError("The dictionary could not be reloaded.")
                self.lookup.dictionary = fresh
                self.lookup.clear_cache()
                if errors:
                    self.finished_work.emit(False, "\n".join(errors))
                else:
                    self.finished_work.emit(True, "Done. New lookups use the updated dictionaries.")
            except Exception as e:
                logger.exception("Dictionary change failed")
                self.finished_work.emit(False, str(e))
        threading.Thread(target=job, name="DictionaryImport", daemon=True).start()

    def _done(self, ok, message):
        self.status.setText(message)
        self.status.setStyleSheet("" if ok else "color: #d9534f;")
        self.refresh()
        self._busy(False)
