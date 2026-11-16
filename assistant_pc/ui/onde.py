"""Visualiseur de la dictée : barres fixes, graves à gauche, aigus à droite, symétriques autour du milieu."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QWidget

GAP = 2
BAR_MAX = 4       # barres fines, alignées à gauche
FALL = 7          # vitesse de redescente d'une barre (points par image)
FLOOR = 18        # en dessous : bruit de fond, trait minimal


class Waveform(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars: list[float] = []
        self.ref = 55.0  # niveau qui remplit la hauteur ; suit les pics (micro faible ou fort)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def clear(self):
        self.bars = []
        self.ref = 55.0
        self.update()

    def push(self, levels: list[int]):
        if len(self.bars) != len(levels):
            self.bars = [0.0] * len(levels)
        peak = max(levels, default=0)
        self.ref = max(55.0, peak, self.ref * 0.995)
        for i, lv in enumerate(levels):
            v = max(0.0, (lv - FLOOR) / (self.ref - FLOOR))
            self.bars[i] = v if v > self.bars[i] else max(v, self.bars[i] - FALL / 100)
        self.update()

    def paintEvent(self, _e):
        if not self.bars:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(QPalette.Text))
        n = len(self.bars)
        w = max(1.5, min(BAR_MAX, (self.width() - GAP * (n - 1)) / n))
        h, mid = self.height(), self.height() / 2
        for i, v in enumerate(self.bars):
            bh = max(2.0, min(1.0, v) * h)
            p.drawRoundedRect(QRectF(i * (w + GAP), mid - bh / 2, w, bh), min(w, bh) / 2, min(w, bh) / 2)
        p.end()
