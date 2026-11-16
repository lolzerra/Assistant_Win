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


# ---------- Pictogrammes des boutons (tracés SVG, couleur au choix) ----------

_SVG = {
    "trombone": '<path d="M21.4 11.1l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
    "micro": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/>'
             '<line x1="12" y1="18" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/>',
    "envoyer": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "capture": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
               '<circle cx="12" cy="12" r="3"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="{c}"/>',
}


def glyph(name: str, color: str, size: int = 64) -> QIcon:
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer

    body = _SVG[name].replace("{c}", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return QIcon(pm)
