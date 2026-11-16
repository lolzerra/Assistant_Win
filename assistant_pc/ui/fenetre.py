"""Fenêtre principale : barre du haut, conversation, pièces jointes et zone de consigne."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu,
                               QPlainTextEdit, QPushButton, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from ..dictee import Dictation
from ..api import MAX_ATTACHMENTS, MAX_FILE_BYTES, Api, AuthError
from . import travail
from .messages import AnswerBubble, UserBubble, bubble_style

THINK_LEVELS = [("Réflexion : auto", None), ("Sans réflexion", 0), ("Réflexion légère", 1),
                ("Réflexion moyenne", 2), ("Réflexion poussée", 3)]


# ---------- Pièces jointes ----------

class Chip(QFrame):
    """Un fichier joint : envoyé au serveur dès qu'il est déposé, retirable avant l'envoi du message."""
    changed = Signal()
    removed = Signal(object)

    def __init__(self, path: Path, api: Api, parent=None):
        super().__init__(parent)
        self.path = path
        self.info: dict | None = None
        self.error: str | None = None
        self.cancelled = False
        self.setObjectName("chip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 2, 2)
        lay.setSpacing(4)
        self.label = QLabel()
        lay.addWidget(self.label)
        x = QToolButton()
        x.setText("✕")
        x.setAutoRaise(True)
        x.setToolTip("Retirer")
        x.clicked.connect(self._remove)
        lay.addWidget(x)
        self._show("⏳")
        travail.run(lambda: api.upload(path), self._uploaded, self._failed)

    @property
    def ready(self) -> bool:
        return self.info is not None

    @property
    def pending(self) -> bool:
        return self.info is None and self.error is None

    def _show(self, state: str, tip: str = ""):
        name = self.path.name if len(self.path.name) <= 28 else self.path.name[:25] + "…"
        self.label.setText(f"{state} {name}")
        self.setToolTip(tip or str(self.path))

    def _uploaded(self, info: dict):
        if self.cancelled:
            return
        self.info = info
        icon = "🖼" if info.get("kind") == "image" else "📄"
        tokens = info.get("tokens")
        self._show(icon, f"{self.path}\n{tokens} tokens" if tokens else str(self.path))
        self.changed.emit()

    def _failed(self, e):
        if self.cancelled:
            return
        self.error = travail.message(e)
        self._show("⚠", self.error)
        self.setStyleSheet("QFrame#chip { border-color: #c0392b; }")
        self.changed.emit()

    def _remove(self):
        self.cancelled = True
        self.removed.emit(self)


class FlowRow(QWidget):
    """Rangée de pièces jointes qui passe à la ligne."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)
        self.items: list[Chip] = []

    def set_items(self, items: list[Chip]):
        self.items = items
        while self.lay.count():
            row = self.lay.takeAt(0).layout()
            while row and row.count():
                row.takeAt(0)
        width = max(self.width(), 300)
        row, used = None, 0
        for chip in items:
            w = chip.sizeHint().width() + 6
            if row is None or used + w > width:
                row = QHBoxLayout()
                row.setSpacing(6)
                row.addStretch()
                self.lay.addLayout(row)
                used = 0
            row.insertWidget(row.count() - 1, chip)
            used += w
        self.setVisible(bool(items))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            QTimer.singleShot(0, lambda: self.set_items(self.items))


class PromptEdit(QPlainTextEdit):
    """Entrée envoie, Maj+Entrée va à la ligne ; coller des fichiers depuis l'Explorateur les joint."""
    submitted = Signal()
    files_pasted = Signal(list)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
            if paths:
                self.files_pasted.emit(paths)
                return
        super().insertFromMimeData(source)


# ---------- Flux de la réponse ----------

class StreamWorker(QObject):
    event = Signal(dict)
    failed = Signal(object)
    finished = Signal(bool)  # True si arrêté par l'utilisateur
    conversation = Signal(int)

    def __init__(self, api: Api, cid: int | None, model: str, payload: dict):
        super().__init__()
        self.api, self.cid, self.model, self.payload = api, cid, model, payload
        self.stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self.stop.set()
        self.api.abort_stream()

    def _run(self):
        try:
            if self.cid is None:
                self.cid = self.api.new_conversation(self.model)
                self.conversation.emit(self.cid)
            for ev in self.api.send(self.cid, self.payload, self.stop):
                self.event.emit(ev)
        except Exception as e:
            if not self.stop.is_set():
                self.failed.emit(e)
        self.finished.emit(self.stop.is_set())


# ---------- Fenêtre ----------

class MainWindow(QWidget):
    auth_lost = Signal()
    open_settings = Signal()
    quit_requested = Signal()

    def __init__(self, config, api: Api, parent=None):
        super().__init__(parent)
        self.config = config
        self.api = api
        self.cid: int | None = None
        self.chips: list[Chip] = []
        self.models: dict[str, dict] = {}
        self.worker: StreamWorker | None = None
        self.answer: AnswerBubble | None = None
        self._done: dict | None = None
        self.really_quit = False

        self.setWindowTitle("Assistant PC")
        self.setAcceptDrops(True)
        self.resize(560, 760)
        self.setMinimumSize(380, 420)

        # Barre du haut
        self.model_box = QComboBox()
        self.model_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model_box.setMinimumContentsLength(12)
        self.model_box.setToolTip("Modèle")
        self.model_box.currentIndexChanged.connect(self._model_changed)
        self.think_box = QComboBox()
        for label, value in THINK_LEVELS:
            self.think_box.addItem(label, value)
        self.think_box.setCurrentIndex(next((i for i, (_, v) in enumerate(THINK_LEVELS)
                                             if v == config["think_level"]), 0))
        self.think_box.currentIndexChanged.connect(self._remember_options)
        self.web = QCheckBox("Web")
        self.web.setToolTip("Recherche web (par le serveur)")
        self.web.setChecked(bool(config["web"]))
        self.web.toggled.connect(self._remember_options)
        new = QToolButton()
        new.setText("➕")
        new.setToolTip("Nouvelle conversation (Ctrl+N)")
        new.setShortcut("Ctrl+N")
        new.clicked.connect(self.new_conversation)
        more = QToolButton()
        more.setText("⋮")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Paramètres…", self.open_settings.emit)
        menu.addSeparator()
        menu.addAction("Quitter", self.quit_requested.emit)
        more.setMenu(menu)

        top = QHBoxLayout()
        top.addWidget(self.model_box, 1)
        top.addWidget(self.think_box)
        top.addWidget(self.web)
        top.addWidget(new)
        top.addWidget(more)

        self.title = QLabel("Nouvelle conversation")
        self.title.setStyleSheet("font-weight: 600;")
        self.title.setTextFormat(Qt.PlainText)

        # Conversation
        self.thread_box = QWidget()
        self.thread = QVBoxLayout(self.thread_box)
        self.thread.setContentsMargins(4, 4, 4, 4)
        self.thread.setSpacing(10)
        self.empty = QLabel("Déposez des fichiers ici (PDF, Word, Excel, images, texte)\n"
                            "puis écrivez votre consigne.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: gray;")
        self.thread.addWidget(self.empty, 1)
        self.thread.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.thread_box)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._follow)
        self._stick = True
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)

        # Bas
        self.chip_row = FlowRow()
        self.chip_row.hide()
        attach = QToolButton()
        attach.setText("📎")
        attach.setToolTip("Joindre des fichiers")
        attach.clicked.connect(self._pick_files)
        self.mic = QToolButton()
        self.mic.setText("🎤")
        self.mic.setCheckable(True)
        self.mic.setToolTip("Dicter (cliquez pour arrêter)")
        self.mic.toggled.connect(self._mic_toggled)
        self.dictation = Dictation(lambda: self.api, lambda: self.prompt.toPlainText())
        self.dictation.text.connect(self._dictated)
        self.dictation.failed.connect(self._dictation_failed)
        self.dictation.running.connect(self._dictation_running)
        self.dictation.busy.connect(lambda b: self.mic.setToolTip("Transcription…" if b else "Dicter (cliquez pour arrêter)"))
        tools = QVBoxLayout()
        tools.setSpacing(4)
        tools.addWidget(attach)
        tools.addWidget(self.mic)
        tools.addStretch()
        self.prompt = PromptEdit()
        self.prompt.setPlaceholderText("Votre consigne… (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)")
        self.prompt.setFixedHeight(76)
        self.prompt.submitted.connect(self.send)
        self.prompt.files_pasted.connect(self.add_files)
        self.send_btn = QPushButton("Envoyer")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._send_or_stop)
        bottom = QHBoxLayout()
        bottom.addLayout(tools)
        bottom.addWidget(self.prompt, 1)
        bottom.addWidget(self.send_btn, 0, Qt.AlignBottom)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setStyleSheet("color: #c0392b;")
        self.status.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(top)
        lay.addWidget(self.title)
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.status)
        lay.addWidget(self.chip_row)
        lay.addLayout(bottom)

        self.setStyleSheet(bubble_style(self) + " QFrame#chip { border: 1px solid palette(mid); border-radius: 10px; }")
        self.apply_on_top()
        self.load_models()

    # ---------- Réglages ----------

    def set_api(self, api: Api):
        if self.worker:
            self.worker.cancel()
        self.api = api
        self.load_models()

    def apply_on_top(self):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(self.config["always_on_top"]))
        if visible:
            self.show()

    def load_models(self):
        travail.run(self.api.models, self._models_loaded, self._models_failed)

    def _models_loaded(self, models: list[dict]):
        self.models = {m["name"]: m for m in models if isinstance(m, dict) and m.get("name")}
        wanted = self.model_box.currentData() or self.config["model"]
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for name, m in self.models.items():
            extra = [x for x in (m.get("params"), "●" if m.get("loaded") else None, "👁" if m.get("vision") else None) if x]
            self.model_box.addItem(f"{name}  {' '.join(extra)}".strip(), name)
        if wanted not in self.models:
            self.model_box.addItem(wanted, wanted)
        self.model_box.setCurrentIndex(max(0, self.model_box.findData(wanted)))
        self.model_box.setToolTip("Modèle · ● chargé en mémoire · 👁 voit les images")
        self.model_box.blockSignals(False)
        self._model_changed()
        if self.status.text().startswith("Modèles"):
            self.show_status("")

    def _models_failed(self, e):
        if isinstance(e, AuthError):
            self.auth_lost.emit()
            return
        if self.model_box.count() == 0:
            self.model_box.addItem(self.config["model"], self.config["model"])
        self.show_status(f"Modèles indisponibles. {travail.message(e)}")

    def _model_changed(self):
        name = self.model_box.currentData()
        if not name:
            return
        m = self.models.get(name, {})
        fixed = m.get("think_mode") in ("none", "always")
        self.think_box.setEnabled(not fixed)
        self.think_box.setToolTip({"none": "Ce modèle ne réfléchit pas",
                                   "always": "Ce modèle réfléchit toujours"}.get(m.get("think_mode"), ""))
        self._remember_options()

    def _remember_options(self):
        if self.model_box.currentData():
            self.config["model"] = self.model_box.currentData()
        self.config["think_level"] = self.think_box.currentData()
        self.config["web"] = self.web.isChecked()
        self.config.save()

    def show_status(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ---------- Fichiers ----------

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Joindre des fichiers", "",
            "Documents et images (*.pdf *.docx *.xlsx *.xlsm *.txt *.md *.csv *.json *.png *.jpg *.jpeg *.webp *.gif *.bmp);;"
            "Tous les fichiers (*)")
        self.add_files(paths)

    def add_files(self, paths: list[str]):
        problems = []
        for p in map(Path, paths):
            if len(self.chips) >= MAX_ATTACHMENTS:
                problems.append(f"{MAX_ATTACHMENTS} pièces jointes au maximum par message.")
                break
            if p.is_dir():
                problems.append(f"{p.name} : les dossiers ne sont pas pris en charge.")
                continue
            try:
                size = p.stat().st_size
            except OSError:
                problems.append(f"{p.name} : fichier introuvable.")
                continue
            if size > MAX_FILE_BYTES:
                problems.append(f"{p.name} : trop lourd (25 Mo maximum).")
                continue
            chip = Chip(p, self.api)
            chip.changed.connect(self._chips_changed)
            chip.removed.connect(self._remove_chip)
            self.chips.append(chip)
        self.show_status("\n".join(problems))
        self._chips_changed()
        self.prompt.setFocus()

    def _remove_chip(self, chip: Chip):
        if chip in self.chips:
            self.chips.remove(chip)
        chip.setParent(None)
        chip.deleteLater()
        self._chips_changed()

    def _chips_changed(self):
        self.chip_row.set_items(self.chips)
        self._update_send()

    def _update_send(self):
        busy = self.worker is not None
        uploading = any(c.pending for c in self.chips)
        self.send_btn.setText("Stop" if busy else ("Envoi…" if uploading else "Envoyer"))
        self.send_btn.setEnabled(busy or not uploading)

    # ---------- Dictée ----------

    def _mic_toggled(self, on: bool):
        if on:
            self.show_status("")
            self.dictation.start()
        else:
            self.dictation.stop()

    def _dictation_running(self, on: bool):
        self.mic.blockSignals(True)
        self.mic.setChecked(on)
        self.mic.blockSignals(False)
        self.mic.setStyleSheet("QToolButton { background: #c0392b; border-radius: 4px; }" if on else "")
        self.prompt.setPlaceholderText("🎤 Je vous écoute… (cliquez de nouveau sur le micro pour arrêter)" if on else
                                       "Votre consigne… (Entrée pour envoyer, Maj+Entrée pour aller à la ligne)")

    def _dictated(self, text: str):
        cur = self.prompt.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        before = self.prompt.toPlainText()
        cur.insertText((" " if before and not before[-1].isspace() else "") + text)
        self.prompt.setTextCursor(cur)

    def _dictation_failed(self, msg: str):
        self.show_status(msg)
        if isinstance(msg, str) and msg.startswith(("Micro", "Impossible")):
            self._dictation_running(False)

    # ---------- Conversation ----------

    def new_conversation(self):
        if self.worker:
            self.worker.cancel()
        self.cid = None
        self._clear_thread()
        self.title.setText("Nouvelle conversation")
        self.show_status("")
        self.prompt.setFocus()

    def _clear_thread(self):
        while self.thread.count() > 2:
            item = self.thread.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self.empty.show()

    def _append(self, widget: QWidget):
        """Questions décalées vers la droite, réponses vers la gauche."""
        self.empty.hide()
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        if isinstance(widget, UserBubble):
            lay.addSpacing(56)
            lay.addWidget(widget, 1)
        else:
            lay.addWidget(widget, 1)
            lay.addSpacing(28)
        self.thread.insertWidget(self.thread.count() - 1, row)

    def _scrolled(self, value):
        bar = self.scroll.verticalScrollBar()
        self._stick = value >= bar.maximum() - 30

    def _follow(self, _min, maximum):
        if self._stick:
            self.scroll.verticalScrollBar().setValue(maximum)

    def _send_or_stop(self):
        if self.worker:
            self.worker.cancel()
        else:
            self.send()

    def send(self):
        if self.worker:
            return
        if any(c.pending for c in self.chips):
            self.show_status("Patientez : des fichiers sont encore en cours d'envoi.")
            return
        failed = [c for c in self.chips if c.error]
        if failed:
            self.show_status("Retirez d'abord les fichiers en erreur (⚠) :\n" +
                             "\n".join(f"{c.path.name} : {c.error}" for c in failed))
            return
        if self.dictation.active:
            self.dictation.stop(flush=False)
        text = self.prompt.toPlainText().strip()
        ready = [c for c in self.chips if c.ready]
        if not text and not ready:
            return
        model = self.model_box.currentData() or self.config["model"]
        if any(c.info.get("kind") == "image" for c in ready) and self.models and not self.models.get(model, {}).get("vision"):
            self.show_status(f"Attention : {model} ne voit pas les images jointes.")
        else:
            self.show_status("")

        payload = {"content": text, "attachments": [c.info["id"] for c in ready], "model": model,
                   "web": self.web.isChecked(), "instructions": self.config["instructions"]}
        if self.think_box.isEnabled() and self.think_box.currentData() is not None:
            payload["think_level"] = self.think_box.currentData()

        self._append(UserBubble(text, [c.info for c in ready]))
        self.answer = AnswerBubble()
        self._append(self.answer)
        self._stick = True
        self.prompt.clear()
        for c in list(self.chips):
            self._remove_chip(c)

        self._done = None
        self.worker = StreamWorker(self.api, self.cid, model, payload)
        self.worker.conversation.connect(self._conversation_created)
        self.worker.event.connect(self._on_event)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()
        self._update_send()

    def _conversation_created(self, cid: int):
        self.cid = cid

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
        if isinstance(ev.get("tool"), dict):
            a.set_step(ev["tool"])
        if isinstance(ev.get("tool_done"), dict):
            a.tool_done(ev["tool_done"])
        if ev.get("error"):
            a.set_error(str(ev["error"]))
        if ev.get("done"):
            self._done = ev
        if isinstance(ev.get("title"), str) and ev["title"]:
            self.title.setText(ev["title"])

    def _on_failed(self, e):
        if self.answer:
            self.answer.set_error(travail.message(e))
        if isinstance(e, AuthError):
            self.auth_lost.emit()

    def _on_finished(self, stopped: bool):
        if self.answer:
            self.answer.finish(self._done, stopped)
        self.worker = None
        self._update_send()
        self.prompt.setFocus()

    # ---------- Fenêtre ----------

    def toggle(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.bring_to_front()

    def bring_to_front(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        self.prompt.setFocus()

    def closeEvent(self, e):
        self.config["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.config.save()
        if self.really_quit:
            e.accept()
        else:
            e.ignore()
            self.hide()
