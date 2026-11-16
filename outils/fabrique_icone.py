"""Écrit build/icone.ico (plusieurs tailles, images PNG) à partir de l'icône dessinée par l'appli."""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from assistant_pc.ui.icone import pixmap  # noqa: E402

app = QGuiApplication(sys.argv)
sizes = [16, 24, 32, 48, 64, 128, 256]
images = []
for s in sizes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pixmap(s).save(buf, "PNG")
    images.append(bytes(buf.data()))

out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icone.ico")
out.parent.mkdir(parents=True, exist_ok=True)
offset = 6 + 16 * len(sizes)
data = struct.pack("<HHH", 0, 1, len(sizes))
for s, png in zip(sizes, images):
    data += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset)
    offset += len(png)
out.write_bytes(data + b"".join(images))
print(f"Icône écrite : {out}")
