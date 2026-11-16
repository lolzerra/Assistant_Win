"""Visualiseur d'onde de la dictée : barres verticales symétriques qui défilent."""
from collections import deque

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QWidget

BAR = 2      # largeur d'une barre
GAP = 2      # espace entre deux barres


class Waveform(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.levels: deque[int] = deque(maxlen=400)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def clear(self):
        self.levels.clear()
        self.update()

    def push(self, level: int):
        self.levels.append(level)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(QPalette.Text))
        h = self.height()
        mid = h / 2
        fit = max(1, self.width() // (BAR + GAP))
        shown = list(self.levels)[-fit:]
        for i, lv in enumerate(shown):
            # niveau 0-100 (dB) → hauteur ; en dessous de ~25 c'est du bruit de fond : trait minimal
            amp = max(0.0, (lv - 25) / 75)
            bh = max(1.5, amp * h)
            p.drawRoundedRect(QRectF(i * (BAR + GAP), mid - bh / 2, BAR, bh), 1, 1)
        p.end()
