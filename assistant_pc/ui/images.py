"""Vignettes et aperçu des images jointes."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
THUMB = 76  # côté de la vignette d'une image jointe


def square_thumb(image: QImage, side: int) -> QPixmap:
    """Vignette carrée : l'image remplit le carré, recadrée au centre."""
    scaled = image.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (scaled.width() - side) // 2, (scaled.height() - side) // 2
    return QPixmap.fromImage(scaled.copy(x, y, side, side))


def load_image(path: Path | None, data: bytes | None) -> QImage:
    if data is not None:
        return QImage.fromData(data)
    if path is not None and path.suffix.lower() in IMAGE_EXT:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > 2000:  # grosse photo : lue réduite
            reader.setScaledSize(size.scaled(2000, 2000, Qt.KeepAspectRatio))
        return reader.read()
    return QImage()


class ImagePreview(QDialog):
    def __init__(self, image: QImage, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        screen = (parent.screen() if parent else QGuiApplication.primaryScreen()).availableGeometry()
        pm = QPixmap.fromImage(image)
        if pm.width() > screen.width() * 0.85 or pm.height() > screen.height() * 0.85:
            pm = pm.scaled(int(screen.width() * 0.85), int(screen.height() * 0.85), Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
        lab = QLabel()
        lab.setPixmap(pm)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(lab)
