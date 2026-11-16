"""Vérification et installation des mises à jour, côté interface."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .. import maj
from ..config import VERSION
from . import travail


class Updater(QObject):
    progress = Signal(int, int)
    before_restart = Signal()   # l'appli libère l'instance unique avant de lancer la nouvelle version
    restart = Signal()          # puis quitte

    def __init__(self, parent_widget_getter, tray):
        super().__init__()
        self._parent = parent_widget_getter
        self.tray = tray
        self.checking = False
        self._cancel = False

    def check(self, manual: bool):
        if self.checking:
            return
        self.checking = True

        def ok(info):
            self.checking = False
            if info["newer"]:
                self._offer(info)
            elif manual:
                QMessageBox.information(self._parent(), "Mises à jour",
                                        f"Vous avez la dernière version ({VERSION}).")

        def err(e):
            self.checking = False
            if manual:
                QMessageBox.warning(self._parent(), "Mises à jour", str(e))

        travail.run(maj.latest, ok, err)

    def _offer(self, info: dict):
        notes = info["notes"][:1200]
        text = f"La version {info['version']} est disponible (vous avez la {VERSION})."
        if not maj.is_frozen():
            QMessageBox.information(self._parent(), "Mise à jour disponible",
                                    text + "\n\nLancé depuis les sources : mettez à jour avec git.")
            return
        box = QMessageBox(QMessageBox.Information, "Mise à jour disponible", text, parent=self._parent())
        if notes:
            box.setDetailedText(notes)
        now = box.addButton("Mettre à jour et relancer", QMessageBox.AcceptRole)
        box.addButton("Plus tard", QMessageBox.RejectRole)
        box.setDefaultButton(now)
        box.exec()
        if box.clickedButton() is now:
            self._download(info)

    def _download(self, info: dict):
        dlg = QProgressDialog(f"Téléchargement de la version {info['version']}…", "Annuler", 0, 100, self._parent())
        dlg.setWindowTitle("Mise à jour")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        self._cancel = False
        dlg.canceled.connect(lambda: setattr(self, "_cancel", True))
        conn = self.progress.connect(lambda done, total: dlg.setValue(int(done * 100 / max(1, total))))

        def ok(path):
            self.progress.disconnect(conn)
            dlg.close()
            try:
                self.before_restart.emit()
                maj.install_and_restart(path)
            except maj.UpdateError as e:
                QMessageBox.warning(self._parent(), "Mise à jour", str(e))
                return
            self.restart.emit()

        def err(e):
            self.progress.disconnect(conn)
            dlg.close()
            if not self._cancel:
                QMessageBox.warning(self._parent(), "Mise à jour", str(e))

        travail.run(lambda: maj.download(info, self.progress.emit, lambda: self._cancel), ok, err)
