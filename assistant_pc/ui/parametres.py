"""Paramètres : serveur, empreinte du certificat, test de connexion, fenêtre, consignes perso, déconnexion."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout)

from ..api import Api, ApiError
from ..config import VERSION, DEFAULT_FINGERPRINT, DEFAULT_URL, normalize_fingerprint, set_start_with_windows
from . import travail
from .connexion import http_warning_label


class SettingsDialog(QDialog):
    logout_requested = Signal()
    check_updates = Signal()

    def __init__(self, config, token: str | None, parent=None):
        super().__init__(parent)
        self.config = config
        self.token = token
        self.setWindowTitle("Assistant PC — Paramètres")
        self.setMinimumWidth(520)

        # Serveur
        self.url = QLineEdit(config["server_url"])
        self.fp = QLineEdit(config["fingerprint"])
        self.fp.setFont(self._mono())
        self.warn = http_warning_label()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        test = QPushButton("Tester la connexion")
        test.clicked.connect(self.test)
        reset = QPushButton("Valeurs par défaut")
        reset.clicked.connect(lambda: (self.url.setText(DEFAULT_URL), self.fp.setText(DEFAULT_FINGERPRINT)))
        server = QGroupBox("Serveur")
        f = QFormLayout(server)
        f.addRow("Adresse", self.url)
        f.addRow("Empreinte SHA-256", self.fp)
        hint = QLabel("Empreinte du certificat https du serveur. À changer seulement quand le certificat est "
                      "renouvelé, après l'avoir vérifiée sur le serveur.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        f.addRow(hint)
        f.addRow(self.warn)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(reset)
        row.addStretch()
        f.addRow(row)
        f.addRow(self.status)

        # Fenêtre
        self.on_top = QCheckBox("Fenêtre toujours au premier plan")
        self.on_top.setChecked(config["always_on_top"])
        self.startup = QCheckBox("Lancer avec Windows (dans la zone de notification)")
        self.startup.setChecked(config["start_with_windows"])
        self.mic = QComboBox()
        self.mic.addItem("Micro par défaut de Windows", "")
        try:
            from ..dictee import microphones
            for name in microphones():
                self.mic.addItem(name, name)
        except Exception as e:
            self.mic.addItem(f"(liste indisponible : {e})", None)
        if config["microphone"] and self.mic.findData(config["microphone"]) < 0:
            self.mic.addItem(f"{config['microphone']} (débranché)", config["microphone"])
        self.mic.setCurrentIndex(max(0, self.mic.findData(config["microphone"])))
        mic_box = QGroupBox("Dictée")
        ml = QFormLayout(mic_box)
        ml.addRow("Micro", self.mic)
        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 100)
        self.mic_level.setTextVisible(False)
        self.mic_level.setFixedHeight(6)
        self.mic_level.setStyleSheet("QProgressBar { border: none; background: palette(mid); border-radius: 3px; }"
                                     "QProgressBar::chunk { background: #2ecc71; border-radius: 3px; }")
        self.mic_note = QLabel("Parlez : la barre doit bouger si le micro choisi capte le son (rien n'est envoyé).")
        self.mic_note.setWordWrap(True)
        self.mic_note.setStyleSheet("color: gray;")
        ml.addRow("", self.mic_level)
        ml.addRow("", self.mic_note)
        self.monitor = None
        try:
            from ..dictee import MicMonitor
            self.monitor = MicMonitor()
            self.monitor.level.connect(self.mic_level.setValue)
            self.monitor.failed.connect(lambda m: (self.mic_note.setText("⚠ " + m),
                                                   self.mic_note.setStyleSheet("color: #c0392b;")))
            self.mic.currentIndexChanged.connect(self._monitor_mic)
            self._monitor_mic()
        except Exception:
            pass

        win = QGroupBox("Fenêtre")
        wl = QVBoxLayout(win)
        wl.addWidget(self.on_top)
        wl.addWidget(self.startup)

        self.auto_update = QCheckBox("Chercher les mises à jour au démarrage (sur GitHub)")
        self.auto_update.setChecked(config["auto_update"])
        upd = QGroupBox(f"Mises à jour — version installée : {VERSION}")
        ul = QHBoxLayout(upd)
        ul.addWidget(self.auto_update)
        ul.addStretch()
        check = QPushButton("Vérifier maintenant")
        check.clicked.connect(self.check_updates.emit)
        ul.addWidget(check)

        # Consignes
        self.instructions = QPlainTextEdit(config["instructions"])
        self.instructions.setPlaceholderText("Ex. : Réponds de façon concise. Tutoie-moi. Montants en euros.")
        self.instructions.setFixedHeight(90)
        ins = QGroupBox("Consignes perso (envoyées avec chaque message)")
        QVBoxLayout(ins).addWidget(self.instructions)

        # Compte
        account = QGroupBox("Compte")
        al = QHBoxLayout(account)
        who = QLabel(f"Connecté : {config['username']}" if token else "Non connecté")
        al.addWidget(who)
        al.addStretch()
        if token:
            out = QPushButton("Se déconnecter")
            out.clicked.connect(self._logout)
            al.addWidget(out)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        for w in (server, mic_box, win, upd, ins, account):
            lay.addWidget(w)
        lay.addWidget(buttons)

        self.url.textChanged.connect(self._url_changed)
        self._url_changed()

    def _monitor_mic(self):
        if self.monitor is None:
            return
        self.mic_note.setText("Parlez : la barre doit bouger si le micro choisi capte le son (rien n'est envoyé).")
        self.mic_note.setStyleSheet("color: gray;")
        name = self.mic.currentData()
        if name is None:
            self.monitor.stop()
        else:
            self.monitor.start(name)

    def done(self, result):
        if self.monitor is not None:
            self.monitor.stop()
        super().done(result)

    @staticmethod
    def _mono():
        from PySide6.QtGui import QFont
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        return f

    def _url_changed(self):
        self.warn.setVisible(self.url.text().strip().lower().startswith("http://"))

    def _show(self, text, error=False):
        self.status.setStyleSheet("color: #c0392b;" if error else "")
        self.status.setText(text)

    def _values(self):
        url = self.url.text().strip().rstrip("/")
        fp = normalize_fingerprint(self.fp.text())
        if url.lower().startswith("https://") and not fp:
            self._show("Empreinte invalide : 32 octets en hexadécimal (64 caractères).", error=True)
            return None
        return url, fp or self.config["fingerprint"]

    def test(self):
        vals = self._values()
        if not vals:
            return
        try:
            api = Api(*vals, token=self.token)
        except ApiError as e:
            self._show(str(e), error=True)
            return
        self._show("Test en cours…")
        travail.run(lambda: (api.ping(), api.close())[0],
                    lambda msg: self._show("✓ " + msg),
                    lambda e: self._show(travail.message(e), error=True))

    def save(self):
        vals = self._values()
        if not vals:
            return
        url, fp = vals
        try:
            Api(url, fp)
        except ApiError as e:
            self._show(str(e), error=True)
            return
        if url.lower().startswith("http://") and url != self.config["server_url"]:
            ok = QMessageBox.warning(self, "Connexion non chiffrée",
                                     "Avec http, le jeton et vos fichiers circulent en clair sur le réseau.\n"
                                     "Utiliser quand même cette adresse ?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ok != QMessageBox.Yes:
                return
        if self.startup.isChecked() != self.config["start_with_windows"]:
            err = set_start_with_windows(self.startup.isChecked())
            if err:
                QMessageBox.information(self, "Lancement avec Windows", err)
            else:
                self.config["start_with_windows"] = self.startup.isChecked()
        self.config.update(server_url=url, fingerprint=fp, always_on_top=self.on_top.isChecked(),
                           auto_update=self.auto_update.isChecked(),
                           microphone=self.mic.currentData() if self.mic.currentData() is not None else "",
                           instructions=self.instructions.toPlainText().strip()[:4000])
        self.config.save()
        self.accept()

    def _logout(self):
        if QMessageBox.question(self, "Déconnexion", "Se déconnecter et supprimer le jeton de ce PC ?") == QMessageBox.Yes:
            self.reject()
            self.logout_requested.emit()
