"""Icône dessinée par le code (pas de fichier à embarquer)."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap


def pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#4f7cff"))
    g.setColorAt(1, QColor("#7a4dff"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    r = size * 0.22
    p.drawRoundedRect(QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92), r, r)
    f = QFont("Segoe UI")
    f.setBold(True)
    f.setPixelSize(int(size * 0.44))
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "IA")
    p.end()
    return pm


def icon() -> QIcon:
    ic = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(pixmap(s))
    return ic
