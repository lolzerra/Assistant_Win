"""Bulles de la conversation : message de l'utilisateur, réponse en Markdown (copie en un clic, réflexion repliée)."""
import html as htmlmod

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)

from . import rendu


class MarkdownView(QTextBrowser):
    """QTextBrowser sans barre verticale, dont la hauteur suit le contenu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setOpenExternalLinks(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QTextBrowser { background: transparent; }")
        self.document().setDefaultStyleSheet(rendu.style_sheet())
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)

    def loadResource(self, rtype, url):  # aucune image ni ressource chargée
        return rendu.blocked_resource(url)

    def _fit(self, *_):
        h = int(self.document().size().height()) + 6
        if self.horizontalScrollBar().isVisible():
            h += self.horizontalScrollBar().height()
        if h != self.height():
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def wheelEvent(self, e):  # la molette fait défiler la conversation, pas la bulle
        e.ignore()


class UserBubble(QFrame):
    def __init__(self, text: str, attachments: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("user")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        if attachments:
            files = QLabel("  ".join(("🖼 " if a.get("kind") == "image" else "📄 ") + a.get("name", "?")
                                     for a in attachments))
            files.setWordWrap(True)
            files.setStyleSheet("color: gray;")
            lay.addWidget(files)
        if text:
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.PlainText)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(lab)


class AnswerBubble(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("answer")
        self.text = ""
        self.thinking = ""
        self.tools: list[dict] = []  # étapes : {"name", …} puis « done » quand le résultat arrive
        self._render_pending = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        self.step = QLabel()
        self.step.setStyleSheet("color: gray;")
        self.step.setWordWrap(True)
        self.step.hide()
        lay.addWidget(self.step)

        self.think_btn = QToolButton()
        self.think_btn.setText("💭 Réflexion ▸")
        self.think_btn.setCheckable(True)
        self.think_btn.setAutoRaise(True)
        self.think_btn.toggled.connect(self._toggle_thinking)
        self.think_btn.hide()
        self.think_view = MarkdownView()
        self.think_view.setStyleSheet("QTextBrowser { background: transparent; color: gray; }")
        self.think_view.hide()
        lay.addWidget(self.think_btn, alignment=Qt.AlignLeft)
        lay.addWidget(self.think_view)

        self.tools_btn = QToolButton()
        self.tools_btn.setCheckable(True)
        self.tools_btn.setAutoRaise(True)
        self.tools_btn.toggled.connect(self._toggle_tools)
        self.tools_btn.hide()
        self.tools_view = MarkdownView()
        self.tools_view.setStyleSheet("QTextBrowser { background: transparent; }")
        self.tools_view.hide()
        lay.addWidget(self.tools_btn, alignment=Qt.AlignLeft)
        lay.addWidget(self.tools_view)

        self.view = MarkdownView()
        lay.addWidget(self.view)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c0392b;")
        self.error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.error.hide()
        lay.addWidget(self.error)

        foot = QHBoxLayout()
        self.stats = QLabel("…")
        self.stats.setStyleSheet("color: gray; font-size: 11px;")
        self.copy_btn = QPushButton("📋 Copier")
        self.copy_btn.setFlat(True)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("Copier la réponse (mise en forme pour Word et Outlook, Markdown pour le reste)")
        self.copy_btn.clicked.connect(self.copy)
        self.copy_btn.setEnabled(False)
        foot.addWidget(self.stats)
        foot.addStretch()
        foot.addWidget(self.copy_btn)
        lay.addLayout(foot)

    # ---------- Flux ----------

    def add_content(self, piece: str):
        self.text += piece
        self._schedule()

    def reset_content(self, text: str):
        self.text = text
        self._schedule()

    def add_thinking(self, piece: str):
        self.thinking += piece
        self.think_btn.show()
        if self.think_btn.isChecked():
            self._schedule()

    def set_step(self, tool: dict):
        self.step.setText(step_label(tool))
        self.step.show()
        self.tools.append(dict(tool))
        self._tools_changed()

    def tool_done(self, info: dict):
        name = info.get("name")
        for t in reversed(self.tools):
            if t.get("name") == name and "done" not in t:
                t.update(info)
                t["done"] = True
                break
        else:
            self.tools.append({**info, "done": True})
        self._tools_changed()

    def set_tools(self, tools: list[dict]):
        self.tools = [{**t, "done": True} for t in tools if isinstance(t, dict)]
        self._tools_changed()

    def _tools_changed(self):
        searches = sum(1 for t in self.tools if t.get("name") == "web_search")
        label = f"🔎 Recherches ({searches})" if searches == len(self.tools) else f"🔎 Recherches et outils ({len(self.tools)})"
        self.tools_btn.setText(label + (" ▾" if self.tools_btn.isChecked() else " ▸"))
        self.tools_btn.setVisible(bool(self.tools))
        if self.tools_btn.isChecked():
            self.tools_view.setHtml(tools_html(self.tools))

    def _toggle_tools(self, on: bool):
        self.tools_view.setVisible(on)
        self._tools_changed()

    def set_error(self, msg: str):
        self.error.setText("⚠ " + msg)
        self.error.show()

    def finish(self, done: dict | None, stopped=False):
        self._render()
        self.step.hide()
        parts = []
        if done:
            if done.get("seconds") is not None:
                parts.append(f"{float(done['seconds']):.1f} s")
            if done.get("tokens"):
                parts.append(f"{done['tokens']} tokens")
            if done.get("tok_s"):
                parts.append(f"{float(done['tok_s']):.1f} tok/s")
        if stopped:
            parts.append("arrêté")
        self.stats.setText(" · ".join(parts))
        self.copy_btn.setEnabled(bool(self.text.strip()))

    def set_static(self, text: str, thinking: str | None, meta: dict, tools: list | None = None):
        """Message déjà enregistré (conversation rouverte)."""
        self.text = text or ""
        if tools:
            self.set_tools(tools)
        if thinking:
            self.thinking = thinking
            self.think_btn.show()
        self.finish(meta)

    # ---------- Affichage ----------

    def _schedule(self):
        if not self._render_pending:
            self._render_pending = True
            QTimer.singleShot(70, self._render)

    def _render(self):
        self._render_pending = False
        self.view.setHtml(rendu.to_html(self.text))
        if self.think_btn.isChecked():
            self.think_view.setHtml(rendu.to_html(self.thinking))

    def _toggle_thinking(self, on: bool):
        self.think_btn.setText("💭 Réflexion ▾" if on else "💭 Réflexion ▸")
        self.think_view.setVisible(on)
        if on:
            self.think_view.setHtml(rendu.to_html(self.thinking))

    def copy(self):
        mime = QMimeData()
        mime.setText(self.text)
        mime.setHtml(rendu.to_html(self.text))
        QGuiApplication.clipboard().setMimeData(mime)
        self.copy_btn.setText("✓ Copié")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("📋 Copier"))


def step_label(tool: dict) -> str:
    name = tool.get("name", "")
    if name == "web_search":
        return f"🔎 Recherche web : {tool.get('query', '')}"
    if name == "fetch_page":
        return f"📄 Lecture de la page : {tool.get('url', '')}"
    detail = next((str(v) for k, v in tool.items() if k not in ("name", "done", "error") and v), "")
    return f"⚙ {name}" + (f" : {detail[:120]}" if detail else "")


def tools_html(tools: list[dict]) -> str:
    esc = htmlmod.escape
    parts = []
    for t in tools:
        line = f"<p><b>{esc(step_label(t))}</b>"
        if t.get("error"):
            line += f"<br><span style='color:#c0392b'>⚠ {esc(str(t['error']))}</span>"
        elif not t.get("done"):
            line += " <i>…</i>"
        line += "</p>"
        results = t.get("results") or []
        if results:
            items = "".join(
                f"<li><a href='{esc(str(r.get('url', '')), quote=True)}'>{esc(str(r.get('title') or r.get('url', '')))}</a></li>"
                for r in results if isinstance(r, dict))
            line += f"<ul>{items}</ul>"
        elif t.get("done") and t.get("name") == "web_search" and not t.get("error"):
            line += "<p style='color:gray'>Aucun résultat.</p>"
        parts.append(line)
    return "".join(parts)


def bubble_style(widget: QWidget) -> str:
    pal = widget.palette()
    dark = pal.color(QPalette.Window).lightness() < 128
    user_bg = "#2f3d5c" if dark else "#e3ecff"
    ans_bg = pal.color(QPalette.Base).name()
    border = "#3a3d42" if dark else "#dde1e6"
    return (f"QFrame#user {{ background: {user_bg}; border-radius: 10px; }}"
            f"QFrame#answer {{ background: {ans_bg}; border: 1px solid {border}; border-radius: 10px; }}")
