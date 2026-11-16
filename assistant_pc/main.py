"""Point d'entrée : instance unique, icône de notification, connexion puis fenêtre principale."""
import getpass
import sys

from PySide6.QtCore import QByteArray, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import coffre, maj
from .api import Api, ApiError
from .config import APP_NAME, VERSION, Config
from .ui import icone, travail
from .ui.connexion import LoginDialog
from .ui.fenetre import MainWindow
from .raccourci import Hotkeys
from .ui.miseajour import Updater
from .ui.parametres import SettingsDialog

SERVER_NAME = f"{APP_NAME}-{getpass.getuser()}"


def dark_palette() -> QPalette:
    p = QPalette()
    base, window, text = QColor("#1e1f22"), QColor("#2b2d31"), QColor("#e6e6e6")
    for role, color in ((QPalette.Window, window), (QPalette.WindowText, text), (QPalette.Base, base),
                        (QPalette.AlternateBase, window), (QPalette.Text, text), (QPalette.Button, window),
                        (QPalette.ButtonText, text), (QPalette.ToolTipBase, window), (QPalette.ToolTipText, text),
                        (QPalette.Highlight, QColor("#4f7cff")), (QPalette.HighlightedText, QColor("white")),
                        (QPalette.Link, QColor("#8ab4ff")), (QPalette.PlaceholderText, QColor("#8a8d93")),
                        (QPalette.Mid, QColor("#4a4d52"))):
        p.setColor(role, color)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#7a7d82"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#7a7d82"))
    return p


class App:
    def __init__(self, qapp: QApplication, server: QLocalServer, start_hidden: bool, updated: bool):
        self.qapp = qapp
        self.server = server
        self.config = Config()
        self.window: MainWindow | None = None
        self.coach_window = None
        self.hotkeys = Hotkeys(qapp)
        maj.cleanup()

        self.tray = QSystemTrayIcon(icone.icon())
        self.tray.setToolTip("Assistant PC")
        menu = QMenu()
        menu.addAction("Afficher", self.show)
        menu.addAction("Nouvelle conversation", self.new_conversation)
        menu.addAction("🎮 Coach en direct…", self.coach)
        menu.addAction("Paramètres…", self.settings)
        menu.addAction("Vérifier les mises à jour", lambda: self.updater.check(manual=True))
        menu.addSeparator()
        quit_action = QAction("Quitter", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()
        self._menu = menu
        self.updater = Updater(lambda: self.window if self.window and self.window.isVisible() else None, self.tray)
        self.updater.before_restart.connect(self.server.close)
        self.updater.restart.connect(self.quit)

        token = coffre.load_token()
        if not token and not self.login():
            raise SystemExit(0)
        self.open_window(Api(self.config["server_url"], self.config["fingerprint"], coffre.load_token()),
                         show=not start_hidden)
        self._register_show_hotkey(quiet=True)
        if updated:
            self.tray.showMessage("Assistant PC", f"Mis à jour en version {VERSION}.", icone.icon(), 4000)
        if self.config["auto_update"]:
            QTimer.singleShot(3000, lambda: self.updater.check(manual=False))

    # ---------- Connexion ----------

    def login(self) -> bool:
        dlg = LoginDialog(self.config)
        dlg.setWindowIcon(icone.icon())
        if dlg.exec() != LoginDialog.Accepted:
            return False
        if not dlg.stored:
            QMessageBox.warning(None, "Coffre Windows",
                                "Le jeton n'a pas pu être rangé dans le Gestionnaire d'identification : "
                                "il faudra vous reconnecter au prochain lancement.")
        if self.window:
            self.window.set_api(dlg.api)
        return True

    def open_window(self, api: Api, show=True):
        self.window = MainWindow(self.config, api)
        self.window.setWindowIcon(icone.icon())
        if self.config["geometry"]:
            self.window.restoreGeometry(QByteArray.fromBase64(self.config["geometry"].encode()))
        self.window.auth_lost.connect(self._auth_lost)
        self.window.open_settings.connect(self.settings)
        self.window.quit_requested.connect(self.quit)
        self.window.check_updates.connect(lambda: self.updater.check(manual=True))
        self.window.coach_requested.connect(self.coach)
        if show:
            self.window.bring_to_front()

    def _auth_lost(self):
        if getattr(self, "_relogging", False):
            return
        self._relogging = True
        try:
            coffre.delete_token()
            self.window.show_status("Session expirée : reconnectez-vous.")
            self.login()
        finally:
            self._relogging = False

    def logout(self):
        api = self.window.api

        def done(_=None):
            coffre.delete_token()
            api.token = None
            self.window.hide()
            if not self.login():
                self.quit()
            else:
                self.window.new_conversation()
                self.window.bring_to_front()

        travail.run(api.logout, done, done)  # même hors ligne, le jeton est retiré de ce PC

    # ---------- Actions ----------

    def show(self):
        self.window.bring_to_front()

    def new_conversation(self):
        self.window.new_conversation()
        self.window.bring_to_front()

    def settings(self):
        dlg = SettingsDialog(self.config, self.window.api.token, self.window)
        dlg.logout_requested.connect(self.logout)
        dlg.check_updates.connect(lambda: self.updater.check(manual=True))
        dlg.coach_requested.connect(lambda: QTimer.singleShot(0, self.coach))
        dlg.hotkey_changed.connect(self._register_show_hotkey)
        old = (self.config["server_url"], self.config["fingerprint"])
        if dlg.exec() == SettingsDialog.Accepted:
            if (self.config["server_url"], self.config["fingerprint"]) != old:
                try:
                    api = Api(self.config["server_url"], self.config["fingerprint"], self.window.api.token)
                except ApiError as e:
                    QMessageBox.warning(self.window, "Paramètres", str(e))
                    return
                self.window.api.close()
                self.window.set_api(api)
            self.window.apply_on_top()

    def _register_show_hotkey(self, quiet=False):
        err = self.hotkeys.register("show", self.config["hotkey"], self.window.toggle)
        if err:
            self.tray.showMessage("Assistant PC", f"Raccourci d'affichage : {err}", icone.icon(), 5000)

    def coach(self):
        from .ui.coach import CoachSetup, CoachWindow
        if self.coach_window is not None:
            self.coach_window.show()
            self.coach_window.raise_()
            self.coach_window.activateWindow()
            return
        w = self.window
        setup = CoachSetup(self.config, w.models, w.model_box.currentData(), w if w.isVisible() else None)
        setup.setWindowIcon(icone.icon())
        if setup.exec() != CoachSetup.Accepted:
            return
        self.coach_window = CoachWindow(self.config, w.api, setup.result_settings(), self.hotkeys, w.models)
        self.coach_window.setWindowIcon(icone.icon())
        self.coach_window.setAttribute(Qt.WA_DeleteOnClose)
        self.coach_window.closed.connect(lambda: setattr(self, "coach_window", None))
        self.coach_window.show()

    def _tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window.toggle()

    def quit(self):
        if self.window:
            self.window.really_quit = True
            self.window.close()
            self.window.api.close()
        self.tray.hide()
        self.qapp.quit()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(icone.icon())
    qapp.setStyle("Fusion")
    if qapp.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        qapp.setPalette(dark_palette())

    # Instance unique : un second lancement réaffiche la fenêtre existante.
    updated = "--apres-maj" in sys.argv
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not updated and sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()

    # Juste après une mise à jour, l'ancienne version peut encore être en train de se fermer.
    if not server.listen(SERVER_NAME) and updated:
        for _ in range(20):
            QLocalServer.removeServer(SERVER_NAME)
            if server.listen(SERVER_NAME):
                break
            QThread.msleep(250)

    app = App(qapp, server, start_hidden="--cache" in sys.argv, updated=updated)

    def other_instance():
        conn = server.nextPendingConnection()
        if conn:
            conn.disconnectFromServer()
        app.show()

    server.newConnection.connect(other_instance)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
