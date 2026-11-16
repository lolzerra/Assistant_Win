"""Écran de connexion : adresse, identifiant, mot de passe. Le mot de passe n'est jamais enregistré."""
import socket

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from .. import coffre
from ..api import Api, ApiError
from . import travail

HTTP_WARNING = ("⚠ Connexion http non chiffrée : le jeton et vos fichiers circulent en clair sur le réseau. "
                "Préférez https://…:8443.")


def http_warning_label() -> QLabel:
    lab = QLabel(HTTP_WARNING)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: #c0392b;")
    return lab


class LoginDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.api: Api | None = None
        self.setWindowTitle("Assistant PC — Connexion")
        self.setMinimumWidth(420)

        self.url = QLineEdit(config["server_url"])
        self.user = QLineEdit(config["username"])
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.warn = http_warning_label()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("Serveur", self.url)
        form.addRow("Identifiant", self.user)
        form.addRow("Mot de passe", self.password)

        test = QPushButton("Tester la connexion")
        test.clicked.connect(self.test)
        buttons = QDialogButtonBox()
        self.ok = buttons.addButton("Se connecter", QDialogButtonBox.AcceptRole)
        buttons.addButton("Annuler", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.login)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        intro = QLabel("Connectez-vous à votre serveur Chat IA. Seul le jeton renvoyé par le serveur est "
                       "gardé, dans le coffre de Windows ; le mot de passe n'est jamais enregistré.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(form)
        lay.addWidget(self.warn)
        lay.addWidget(test, alignment=Qt.AlignLeft)
        lay.addWidget(self.status)
        lay.addWidget(buttons)

        self.url.textChanged.connect(self._url_changed)
        self._url_changed()
        (self.password if config["username"] else self.user).setFocus()

    def _url_changed(self):
        self.warn.setVisible(self.url.text().strip().lower().startswith("http://"))

    def _make_api(self) -> Api | None:
        try:
            return Api(self.url.text().strip(), self.config["fingerprint"])
        except ApiError as e:
            self._show(str(e), error=True)
            return None

    def _show(self, text: str, error=False):
        self.status.setStyleSheet("color: #c0392b;" if error else "")
        self.status.setText(text)

    def _busy(self, busy: bool):
        self.ok.setEnabled(not busy)
        if busy:
            self._show("Connexion en cours…")

    def test(self):
        api = self._make_api()
        if not api:
            return
        self._busy(True)
        travail.run(api.ping,
                    lambda msg: (self._busy(False), self._show("✓ " + msg)),
                    lambda e: (self._busy(False), self._show(travail.message(e), error=True)))

    def login(self):
        api = self._make_api()
        if not api:
            return
        username, password = self.user.text().strip(), self.password.text()
        if not username or not password:
            self._show("Indiquez l'identifiant et le mot de passe.", error=True)
            return
        self._busy(True)
        device = f"PC {socket.gethostname()}"[:100]
        travail.run(lambda: api.login(username, password, device),
                    lambda res: self._logged(api, username, res),
                    lambda e: (self._busy(False), self._show(travail.message(e), error=True)))

    def _logged(self, api: Api, username: str, res: dict):
        self.password.clear()
        token = res.get("token")
        if not token:
            self._busy(False)
            self._show("Réponse inattendue du serveur (pas de jeton).", error=True)
            return
        api.token = token
        stored = coffre.save_token(username, token)
        self.config["server_url"] = api.base_url
        self.config["username"] = username
        self.config.save()
        self.api = api
        self.stored = stored
        self.accept()
