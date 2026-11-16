"""Coach en direct : à chaque appui sur le raccourci, une capture du jeu part au modèle, qui donne le score,
les stats du joueur (repéré par son pseudo) et des conseils pour la suite de la partie."""
from datetime import datetime

from PySide6.QtCore import QBuffer, QIODevice, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QPushButton, QRadioButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from ..api import MAX_FILE_BYTES, Api, AuthError
from ..raccourci import ElevatedRelay, is_admin
from . import travail
from .capture import grab_screen, grab_window, list_windows
from .fenetre import StreamWorker
from .messages import AnswerBubble, UserBubble, bubble_style

PREVIEW_W, PREVIEW_H = 480, 270


def coach_instructions(pseudo: str, game: str) -> str:
    jeu = f" pour {game}" if game else ""
    return (
        f"Tu es un coach de jeu vidéo en direct{jeu}. Le joueur que tu coaches a pour pseudo « {pseudo} » : "
        "repère-le sur les captures (tableau des scores, nom au-dessus du personnage, fil des éliminations…).\n"
        "À chaque capture d'écran, réponds en français et très brièvement (il lit en pleine partie), en trois parties :\n"
        "**Score** : le score de la partie tel qu'il est affiché (équipes, manches, temps restant si visible).\n"
        f"**Stats de {pseudo}** : ses statistiques visibles (éliminations, morts, assistances, argent, niveau, objets…).\n"
        "**Conseils** : 2 à 4 conseils concrets pour la suite de la partie, tirés de ce que tu vois et de "
        "l'évolution depuis les captures précédentes.\n"
        "N'invente rien : si une information n'est pas visible sur la capture, dis-le en un mot."
    )


def screen_label(i: int, screen) -> str:
    g = screen.geometry()
    dpr = screen.devicePixelRatio()
    main = " (principal)" if screen is QGuiApplication.primaryScreen() else ""
    return f"Écran {i}{main} — {round(g.width() * dpr)} × {round(g.height() * dpr)}"


# ---------- Préparation ----------

class CoachSetup(QDialog):
    """Choix de la source (écran ou fenêtre) avec aperçu toutes les 0,5 s, pseudo, jeu, modèle, raccourci."""

    def __init__(self, config, models: dict, current_model: str | None, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Coach en direct — préparation")
        self.setMinimumWidth(540)

        self.by_screen = QRadioButton("Écran entier")
        self.by_window = QRadioButton("Fenêtre")
        group = QButtonGroup(self)
        group.addButton(self.by_screen)
        group.addButton(self.by_window)
        (self.by_window if config["coach_source"] == "window" else self.by_screen).setChecked(True)
        self.target = QComboBox()
        self.target.setMinimumContentsLength(30)
        self.target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Actualiser la liste")
        refresh.clicked.connect(self._fill_targets)
        self.by_screen.toggled.connect(self._fill_targets)

        self.preview = QLabel("Aperçu…")
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background: #111; color: gray; border-radius: 6px;")
        self.preview_note = QLabel("Aperçu actualisé toutes les 0,5 s : vérifiez que c'est bien votre jeu.")
        self.preview_note.setStyleSheet("color: gray;")

        self.pseudo = QLineEdit(config["coach_pseudo"])
        self.pseudo.setPlaceholderText("Votre pseudo dans le jeu (obligatoire)")
        self.game = QLineEdit(config["coach_game"])
        self.game.setPlaceholderText("Ex. : Valorant, League of Legends, Rocket League… (facultatif)")
        self.model = QComboBox()
        vision = [n for n, m in models.items() if m.get("vision")]
        for name in vision or list(models) or [current_model or config["model"]]:
            self.model.addItem(name, name)
        wanted = config["coach_model"] or (current_model if current_model in vision else None)
        if wanted and self.model.findData(wanted) >= 0:
            self.model.setCurrentIndex(self.model.findData(wanted))
        self.model_note = QLabel("" if vision or not models else "⚠ Aucun modèle ne voit les images : le coach ne pourra pas lire les captures.")
        self.model_note.setStyleSheet("color: #c0392b;")
        self.model_note.setVisible(bool(self.model_note.text()))
        self.key = QKeySequenceEdit(QKeySequence(config["coach_hotkey"]))
        self.key.setMaximumSequenceLength(1)
        self.admin = QCheckBox("Le jeu tourne en administrateur (League of Legends, Valorant…) :\n"
                               "capter le raccourci avec les droits administrateur (confirmation Windows)")
        self.admin.setChecked(bool(config["coach_admin"]))
        self.game.textChanged.connect(self._guess_admin)
        if is_admin():
            self.admin.setChecked(False)
            self.admin.setEnabled(False)
            self.admin.setText("L'appli tourne déjà en administrateur : le raccourci marche dans tous les jeux")

        src = QHBoxLayout()
        src.addWidget(self.by_screen)
        src.addWidget(self.by_window)
        src.addStretch()
        tgt = QHBoxLayout()
        tgt.addWidget(self.target, 1)
        tgt.addWidget(refresh)
        form = QFormLayout()
        form.addRow("Capturer", src)
        form.addRow("", tgt)
        form.addRow("", self.preview)
        form.addRow("", self.preview_note)
        form.addRow("Pseudo", self.pseudo)
        form.addRow("Jeu", self.game)
        form.addRow("Modèle", self.model)
        form.addRow("", self.model_note)
        form.addRow("Raccourci de capture", self.key)
        form.addRow("", self.admin)

        buttons = QDialogButtonBox()
        self.start = buttons.addButton("Démarrer le coaching", QDialogButtonBox.AcceptRole)
        buttons.addButton("Annuler", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b;")
        self.error.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(buttons)

        self._fill_targets()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_preview)
        self.timer.start(500)
        self._refresh_preview()

    def _guess_admin(self, text: str):
        if self.admin.isEnabled() and any(k in text.lower() for k in ("league", "lol", "valorant")):
            self.admin.setChecked(True)

    def _fill_targets(self, *_):
        self.target.blockSignals(True)
        self.target.clear()
        if self.by_screen.isChecked():
            for i, sc in enumerate(QGuiApplication.screens(), 1):
                self.target.addItem(screen_label(i, sc), ("screen", sc.name()))
            wanted = ("screen", self.config["coach_target"])
        else:
            for hwnd, title, _rect in list_windows():
                if title.strip():
                    self.target.addItem(title[:80], ("window", hwnd))
            if self.target.count() == 0:
                self.target.addItem("(aucune fenêtre trouvée)", None)
            wanted = None
            for i in range(self.target.count()):
                d = self.target.itemData(i)
                if d and self.target.itemText(i) == self.config["coach_target"]:
                    wanted = d
        if wanted is not None and self.target.findData(wanted) >= 0:
            self.target.setCurrentIndex(self.target.findData(wanted))
        self.target.blockSignals(False)
        self._refresh_preview()

    def grab(self):
        return grab_target(self.target.currentData())

    def _refresh_preview(self):
        img = self.grab()
        if img is None or img.isNull():
            self.preview.setText("Aucune image : fenêtre fermée ou réduite ?")
            return
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(PREVIEW_W, PREVIEW_H, Qt.KeepAspectRatio,
                                                             Qt.SmoothTransformation))

    def _accept(self):
        pseudo = self.pseudo.text().strip()
        if not pseudo:
            self.error.setText("Indiquez votre pseudo : le coach s'en sert pour vous repérer sur les captures.")
            return
        if not self.target.currentData():
            self.error.setText("Choisissez l'écran ou la fenêtre à capturer.")
            return
        seq = self.key.keySequence().toString()
        if not seq:
            self.error.setText("Choisissez un raccourci de capture.")
            return
        kind = self.target.currentData()[0]
        self.config.update(coach_pseudo=pseudo, coach_game=self.game.text().strip(), coach_hotkey=seq,
                           coach_source=kind, coach_model=self.model.currentData() or "",
                           coach_admin=self.admin.isChecked(),
                           coach_target=(self.target.currentData()[1] if kind == "screen"
                                         else self.target.currentText()))
        self.config.save()
        self.timer.stop()
        self.accept()

    def result_settings(self) -> dict:
        return {"target": self.target.currentData(), "title": self.target.currentText(),
                "pseudo": self.config["coach_pseudo"], "game": self.config["coach_game"],
                "model": self.config["coach_model"], "hotkey": self.config["coach_hotkey"],
                "admin": self.config["coach_admin"]}

    def done(self, r):
        self.timer.stop()
        super().done(r)


def grab_target(target):
    if not target:
        return None
    kind, ref = target
    if kind == "screen":
        screen = next((s for s in QGuiApplication.screens() if s.name() == ref), None)
        return grab_screen(screen) if screen else None
    return grab_window(ref)


# ---------- Fenêtre du coach ----------

class CoachStream(StreamWorker):
    """Envoie d'abord la capture au serveur, puis le message, puis lit la réponse en flux."""

    def __init__(self, api: Api, cid, model: str, payload: dict, png: bytes, name: str):
        super().__init__(api, cid, model, payload)
        self.png, self.name = png, name

    def _run(self):
        try:
            info = self.api.upload_bytes(self.png, self.name)
            self.payload["attachments"] = [info["id"]]
        except Exception as e:
            self.failed.emit(e)
            self.finished.emit(False)
            return
        super()._run()


class CoachWindow(QWidget):
    closed = Signal()

    def __init__(self, config, api: Api, settings: dict, hotkeys, models: dict):
        super().__init__(None, Qt.Window)
        self.config, self.api, self.s, self.hotkeys = config, api, settings, hotkeys
        self.model_info = models.get(settings["model"], {})
        self.cid = None
        self.count = 0
        self.worker: CoachStream | None = None
        self.answer: AnswerBubble | None = None
        self.pending = None
        self._done = None

        game = settings["game"] or "Coach en direct"
        self.setWindowTitle(f"🎮 {game} — {settings['pseudo']}")
        self.resize(520, 760)

        self.status = QLabel()
        self.status.setWordWrap(True)
        now = QPushButton("📸 Analyser maintenant")
        now.clicked.connect(self.trigger)
        self.on_top = QCheckBox("Toujours au premier plan")
        self.on_top.toggled.connect(self._set_on_top)
        self.admin_btn = QPushButton("🛡 Mode administrateur")
        self.admin_btn.setToolTip("Si le raccourci ne marche pas en jeu (jeu lancé en administrateur, comme LoL) : "
                                  "le raccourci sera capté avec les droits administrateur")
        self.admin_btn.clicked.connect(self._start_relay)
        self.admin_btn.setVisible(not is_admin())
        self.relay: ElevatedRelay | None = None
        self.closing = False
        stop = QPushButton("Terminer")
        stop.clicked.connect(self.close)
        head = QHBoxLayout()
        head.addWidget(now)
        head.addWidget(self.on_top)
        head.addStretch()
        head.addWidget(self.admin_btn)
        head.addWidget(stop)
        source = QLabel(f"Source : {settings['title']} · Modèle : {settings['model']}")
        source.setStyleSheet("color: gray; font-size: 11px;")

        self.thread_box = QWidget()
        self.thread = QVBoxLayout(self.thread_box)
        self.thread.setSpacing(10)
        self.thread.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.thread_box)
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _a, b: self.scroll.verticalScrollBar().setValue(b))

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(source)
        lay.addWidget(self.status)
        lay.addWidget(self.scroll, 1)
        self.setStyleSheet(bubble_style(self))

        if settings.get("admin") and not is_admin():
            self._start_relay()
        else:
            err = hotkeys.register("coach", settings["hotkey"], self.trigger)
            if err:
                self._status(f"⚠ {err}. Utilisez le bouton « Analyser maintenant » ou changez de raccourci.", True)
            else:
                self._status(f"Appuyez sur {self._key()} en jeu pour analyser la partie. "
                             "Rien ne se passe en jeu ? Cliquez sur « 🛡 Mode administrateur ».")

    def _key(self) -> str:
        return QKeySequence(self.s["hotkey"]).toString(QKeySequence.NativeText)

    def _start_relay(self):
        self.hotkeys.unregister("coach")  # le relais prend la touche à sa place
        if self.relay is None:
            self.relay = ElevatedRelay()
            self.relay.pressed.connect(self.trigger)
            self.relay.state.connect(self._relay_state)
        self.admin_btn.setEnabled(False)
        self._status("Confirmez l'autorisation administrateur demandée par Windows…")
        self.relay.start(self.s["hotkey"])

    def _relay_state(self, active: bool, msg: str):
        if self.closing:
            return
        if active:
            self.admin_btn.setText("🛡 Administrateur actif")
            self._status(f"Appuyez sur {self._key()} en jeu pour analyser la partie (raccourci capté en administrateur).")
            return
        if msg.startswith("Démarrage"):
            self._status(msg)
            return
        self.admin_btn.setEnabled(True)
        self.admin_btn.setText("🛡 Mode administrateur")
        self._status(f"⚠ {msg}", True)
        self.hotkeys.register("coach", self.s["hotkey"], self.trigger)  # repli : raccourci normal

    def _status(self, text: str, error=False):
        self.status.setStyleSheet("color: #c0392b;" if error else "color: gray;")
        self.status.setText(text)

    def _set_on_top(self, on: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

    # ---------- Captures ----------

    def trigger(self):
        img = grab_target(self.s["target"])
        if img is None or img.isNull():
            self._status("⚠ Capture impossible : la fenêtre du jeu est-elle fermée ou réduite ?", True)
            return
        if self.worker is not None:
            self.pending = img  # une seule en attente : la plus récente
            self._status("Capture prise : elle partira dès la fin de la réponse en cours.")
            return
        self._send(img)

    def _send(self, img):
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        png = bytes(buf.data())
        if len(png) > MAX_FILE_BYTES:  # très grand écran : JPEG à la place
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "JPG", 90)
            png = bytes(buf.data())
        ext = "png" if png[:4] == b"\x89PNG" else "jpg"
        self.count += 1
        at = datetime.now()
        name = f"coach-{at:%Y%m%d-%H%M%S}.{ext}"
        text = f"Capture n° {self.count} ({at:%H:%M:%S})."
        instructions = coach_instructions(self.s["pseudo"], self.s["game"])
        if self.config["instructions"]:
            instructions = (self.config["instructions"] + "\n\n" + instructions)[-4000:]
        payload = {"content": text, "model": self.s["model"], "web": False, "instructions": instructions}
        if self.model_info.get("think_mode") in ("toggle", "levels"):
            payload["think_level"] = 0  # réponse rapide : il lit en jouant

        self._append(UserBubble(text, [{"name": name, "image": img, "kind": "image"}]))
        self.answer = AnswerBubble()
        self._append(self.answer)
        self._done = None
        self._status("Analyse en cours…")
        self.worker = CoachStream(self.api, self.cid, self.s["model"], payload, png, name)
        self.worker.conversation.connect(lambda cid: setattr(self, "cid", cid))
        self.worker.event.connect(self._on_event)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _append(self, w: QWidget):
        self.thread.insertWidget(self.thread.count() - 1, w)

    def _on_event(self, ev: dict):
        a = self.answer
        if a is None:
            return
        if "content_reset" in ev:
            a.reset_content(str(ev["content_reset"]))
        if isinstance(ev.get("content"), str):
            a.add_content(ev["content"])
        if isinstance(ev.get("thinking"), str):
            a.add_thinking(ev["thinking"])
        if ev.get("error"):
            a.set_error(str(ev["error"]))
        if ev.get("done"):
            self._done = ev

    def _on_failed(self, e):
        if self.answer:
            self.answer.set_error(travail.message(e))
        if isinstance(e, AuthError):
            self._status("⚠ Session expirée : reconnectez-vous depuis la fenêtre principale.", True)

    def _on_finished(self, stopped: bool):
        if self.answer:
            self.answer.finish(self._done, stopped)
        self.worker = None
        key = QKeySequence(self.s["hotkey"]).toString(QKeySequence.NativeText)
        self._status(f"Appuyez sur {key} en jeu pour une nouvelle analyse.")
        if self.pending is not None:
            img, self.pending = self.pending, None
            self._send(img)

    def closeEvent(self, e):
        self.closing = True
        self.hotkeys.unregister("coach")
        if self.relay is not None:
            self.relay.stop()
        if self.worker:
            self.worker.cancel()
        self.closed.emit()
        super().closeEvent(e)
