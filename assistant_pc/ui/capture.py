"""Capture d'écran : écran entier, rectangle libre ou fenêtre. L'image reste sur le PC jusqu'à son envoi au serveur.

Chaque écran est photographié avant d'afficher quoi que ce soit, puis un calque plein écran par écran
montre cette photo : on y trace un rectangle, ou on clique sur une fenêtre (repérée par Windows).
Coordonnées : Qt travaille en pixels logiques ; le coin d'un écran est le même en logique et en natif,
seule la taille est multipliée par le facteur d'échelle (devicePixelRatio).
"""
import os
import sys

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QDialog, QLabel, QMenu, QVBoxLayout, QWidget


# ---------- Fenêtres de Windows ----------

def native_windows() -> list[tuple[QRect, str]]:
    """Fenêtres visibles, de la plus haute à la plus basse : (rectangle natif, titre). Vide hors Windows."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    me = os.getpid()
    found: list[tuple[QRect, str]] = []
    GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x80
    DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me or user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        cloaked = wintypes.DWORD()
        dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            return True
        r = wintypes.RECT()
        if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        if rect.width() < 40 or rect.height() < 30:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        found.append((rect, buf.value))
        return True

    user32.EnumWindows(visit, 0)
    return found


# ---------- Calque de sélection ----------

class Shot:
    """Photo d'un écran et conversions de coordonnées."""

    def __init__(self, screen):
        self.screen = screen
        self.geo = screen.geometry()
        self.dpr = screen.devicePixelRatio()
        self.pixmap: QPixmap = screen.grabWindow(0)
        self.pixmap.setDevicePixelRatio(self.dpr)

    def native_rect(self) -> QRect:
        return QRect(self.geo.topLeft(), (self.geo.size().toSizeF() * self.dpr).toSize())

    def to_native(self, local: QPoint) -> QPoint:
        return self.geo.topLeft() + QPoint(round(local.x() * self.dpr), round(local.y() * self.dpr))

    def native_to_local(self, r: QRect) -> QRect:
        o = self.geo.topLeft()
        return QRect(round((r.x() - o.x()) / self.dpr), round((r.y() - o.y()) / self.dpr),
                     round(r.width() / self.dpr), round(r.height() / self.dpr))

    def crop_local(self, r: QRect) -> QPixmap:
        phys = QRect(round(r.x() * self.dpr), round(r.y() * self.dpr),
                     round(r.width() * self.dpr), round(r.height() * self.dpr))
        out = self.pixmap.copy(phys)
        out.setDevicePixelRatio(1)
        return out

    def crop_native(self, r: QRect) -> QPixmap:
        part = r.intersected(self.native_rect()).translated(-self.geo.topLeft())
        out = self.pixmap.copy(part)
        out.setDevicePixelRatio(1)
        return out


class Overlay(QWidget):
    picked = Signal(object)   # QPixmap
    cancelled = Signal()

    def __init__(self, shot: Shot, mode: str, windows: list[tuple[QRect, str]]):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.shot, self.mode, self.windows = shot, mode, windows
        self.origin: QPoint | None = None
        self.sel = QRect()
        self.hover: tuple[QRect, str] | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor if mode == "rectangle" else Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)  # redessine à l'entrée et à la sortie de la souris (mode écran)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()
        self.setGeometry(shot.geo)

    # Rectangle libre
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.cancelled.emit()
            return
        if self.mode == "rectangle":
            self.origin = e.position().toPoint()
            self.sel = QRect(self.origin, self.origin)
        elif self.mode == "ecran":
            pm = self.shot.pixmap.copy()
            pm.setDevicePixelRatio(1)
            self.picked.emit(pm)
        elif self.hover:
            pm = self.shot.crop_native(self.hover[0])
            if not pm.isNull():
                self.picked.emit(pm)

    def mouseMoveEvent(self, e):
        p = e.position().toPoint()
        if self.mode == "rectangle":
            if self.origin is not None:
                self.sel = QRect(self.origin, p).normalized()
        elif self.mode == "fenetre":
            native = self.shot.to_native(p)
            self.hover = next(((r, t) for r, t in self.windows if r.contains(native)), None)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.mode == "rectangle" and self.origin is not None:
            self.origin = None
            if self.sel.width() > 4 and self.sel.height() > 4:
                self.picked.emit(self.shot.crop_local(self.sel))
            else:
                self.sel = QRect()
                self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.shot.pixmap)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        target = QRect()
        label = ""
        if self.mode == "rectangle" and not self.sel.isNull():
            target = self.sel
            label = f"{round(self.sel.width() * self.shot.dpr)} × {round(self.sel.height() * self.shot.dpr)}"
        elif self.mode == "ecran" and self.underMouse():
            target = self.rect()
            label = f"{self.shot.screen.name()} — {self.shot.pixmap.width()} × {self.shot.pixmap.height()}"
        elif self.mode == "fenetre" and self.hover:
            target = self.shot.native_to_local(self.hover[0]).intersected(self.rect())
            label = self.hover[1]
        if self.mode == "ecran" and not target.isNull():
            p.drawPixmap(0, 0, self.shot.pixmap)
            p.setPen(QPen(QColor("#4f7cff"), 6))
            p.drawRect(self.rect().adjusted(3, 3, -3, -3))
        elif not target.isNull():
            src = QRect(round(target.x() * self.shot.dpr), round(target.y() * self.shot.dpr),
                        round(target.width() * self.shot.dpr), round(target.height() * self.shot.dpr))
            p.drawPixmap(target, self.shot.pixmap, src)
            p.setPen(QPen(QColor("#4f7cff"), 2))
            p.drawRect(target.adjusted(0, 0, -1, -1))
        hint = {"rectangle": "Glissez pour sélectionner une zone", "fenetre": "Cliquez sur une fenêtre",
                "ecran": "Cliquez sur l'écran à capturer"}[self.mode] + " · Échap ou clic droit pour annuler"
        if label:
            hint = f"{label}   —   {hint}"
        f = p.font()
        f.setPointSize(11)
        p.setFont(f)
        box = p.fontMetrics().boundingRect(hint).adjusted(-12, -6, 12, 6)
        box.moveCenter(QPoint(self.width() // 2, 30))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 210))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignCenter, hint)
        p.end()


class ScreenThumb(QAbstractButton):
    """Miniature d'un écran, numérotée, surlignée au survol. Clic droit : capture dans l'état actuel."""
    live = Signal(object)

    def __init__(self, shot: Shot, number: int, primary: bool, parent=None):
        super().__init__(parent)
        self.shot, self.number, self.primary = shot, number, primary
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Écran {number}{' (principal)' if primary else ''} — "
                        f"{shot.pixmap.width()} × {shot.pixmap.height()}")
        self.setAttribute(Qt.WA_Hover)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction("Capturer dans l'état actuel", lambda: self.live.emit(self.shot.screen))
        menu.exec(e.globalPos())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(3, 3, -3, -3)
        p.drawPixmap(r, self.shot.pixmap, self.shot.pixmap.rect())
        if not self.underMouse():
            p.fillRect(r, QColor(0, 0, 0, 70))
        p.setPen(QPen(QColor("#4f7cff") if self.underMouse() else QColor(128, 128, 128), 3 if self.underMouse() else 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        badge = QRect(r.x() + 6, r.y() + 6, 26, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#4f7cff") if self.underMouse() else QColor(20, 20, 20, 200))
        p.drawEllipse(badge)
        p.setPen(QColor("white"))
        f = p.font()
        f.setBold(True)
        f.setPointSize(11)
        p.setFont(f)
        p.drawText(badge, Qt.AlignCenter, str(self.number))
        p.end()


class ScreenPicker(QDialog):
    """Miniatures de tous les écrans, placées comme les écrans eux-mêmes ; un clic choisit l'écran."""
    picked = Signal(object)

    MAX_W, MAX_H = 640, 360

    def __init__(self, shots: list[Shot], anchor: QPoint | None):
        super().__init__(None, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Capture d'écran — choisissez l'écran")
        rects = [sh.native_rect() for sh in shots]
        box = rects[0]
        for r in rects[1:]:
            box = box.united(r)
        scale = min(self.MAX_W / box.width(), self.MAX_H / box.height())
        canvas = QWidget()
        canvas.setFixedSize(round(box.width() * scale), round(box.height() * scale))
        primary = QGuiApplication.primaryScreen()
        for i, (sh, r) in enumerate(zip(shots, rects), 1):
            t = ScreenThumb(sh, i, sh.screen is primary, canvas)
            t.setGeometry(round((r.x() - box.x()) * scale), round((r.y() - box.y()) * scale),
                          round(r.width() * scale), round(r.height() * scale))
            t.clicked.connect(lambda _=False, sh=sh: self._pick(sh))
            t.live.connect(self._live)
        self.live_screen = None
        hint = QLabel("Cliquez sur l'écran à capturer · clic droit : capture de l'état actuel · Échap pour annuler")
        hint.setStyleSheet("color: gray;")
        lay = QVBoxLayout(self)
        lay.addWidget(canvas, alignment=Qt.AlignCenter)
        lay.addWidget(hint, alignment=Qt.AlignCenter)
        self.adjustSize()
        if anchor is not None:  # à l'endroit où était l'appli
            g = self.frameGeometry()
            g.moveCenter(anchor)
            area = (QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()).availableGeometry()
            g.moveLeft(max(area.left(), min(g.left(), area.right() - g.width())))
            g.moveTop(max(area.top(), min(g.top(), area.bottom() - g.height())))
            self.move(g.topLeft())

    def _live(self, screen):
        self.live_screen = screen
        self.accept()

    def _pick(self, shot: Shot):
        pm = shot.pixmap.copy()
        pm.setDevicePixelRatio(1)
        self.picked.emit(pm)
        self.accept()


class Capture(QObject):
    """Mène une capture : la fenêtre de l'appli est masquée par l'appelant avant start()."""
    done = Signal(object)  # QPixmap, ou None si annulée

    def __init__(self):
        super().__init__()
        self.overlays: list[Overlay] = []

    def start(self, mode: str, anchor: QPoint | None = None):
        # Laisse à Windows le temps d'effacer la fenêtre de l'appli avant la photo.
        self.anchor = anchor
        QTimer.singleShot(250, lambda: self._grab(mode))

    def _grab(self, mode: str):
        screens = QGuiApplication.screens()
        if mode == "ecran":
            shots = [Shot(sc) for sc in screens]
            if len(shots) == 1:  # un seul écran : pas besoin de choisir
                pm = shots[0].pixmap
                pm.setDevicePixelRatio(1)
                self.done.emit(pm)
                return
            self.picker = ScreenPicker(shots, self.anchor)
            result = []
            self.picker.picked.connect(result.append)
            self.picker.exec()
            live = self.picker.live_screen
            self.picker = None
            if live is not None:  # nouvelle photo, une fois la fenêtre de choix effacée
                QTimer.singleShot(250, lambda: self._grab_now(live))
                return
            self.done.emit(result[0] if result else None)
            return
        windows = native_windows() if mode == "fenetre" else []
        if mode == "fenetre" and not windows:
            mode = "rectangle"  # hors Windows : pas de liste des fenêtres
        for screen in screens:
            ov = Overlay(Shot(screen), mode, windows)
            ov.picked.connect(self._finish)
            ov.cancelled.connect(lambda: self._finish(None))
            if hasattr(ov, "setScreen"):
                ov.setScreen(screen)
            ov.setGeometry(screen.geometry())
            ov.showFullScreen()
            ov.setGeometry(screen.geometry())  # certaines configurations multi-écrans ignorent le premier placement
            self.overlays.append(ov)
        under = QGuiApplication.screenAt(QCursor.pos())
        for ov in self.overlays:
            if ov.shot.screen is under:
                ov.activateWindow()
                ov.raise_()
                ov.setFocus()

    def _grab_now(self, screen):
        if screen not in QGuiApplication.screens():
            self.done.emit(None)
            return
        pm = Shot(screen).pixmap
        pm.setDevicePixelRatio(1)
        self.done.emit(pm)

    def _finish(self, pixmap):
        for ov in self.overlays:
            ov.close()
        self.overlays = []
        self.done.emit(pixmap)
