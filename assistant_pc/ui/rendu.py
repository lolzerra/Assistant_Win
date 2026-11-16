"""Markdown → HTML pour QTextBrowser (tableaux, listes, code). Le HTML brut du modèle est affiché comme du texte."""
import html as htmlmod

import markdown
from PySide6.QtCore import QUrl
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

_md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
# Pas de HTML brut : ni balises du modèle interprétées, ni images ou liens cachés.
_md.preprocessors.deregister("html_block")
_md.inlinePatterns.deregister("html")


def to_html(text: str) -> str:
    _md.reset()
    try:
        body = _md.convert(text)
    except Exception:
        body = f"<pre>{htmlmod.escape(text)}</pre>"
    return body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="5" width="100%">')


def style_sheet() -> str:
    pal = QApplication.palette()
    dark = pal.color(QPalette.Window).lightness() < 128
    code_bg = "#2b2d31" if dark else "#f2f3f5"
    border = "#55585e" if dark else "#c8ccd2"
    link = pal.color(QPalette.Link).name()
    return f"""
        body {{ line-height: 135%; }}
        p {{ margin-top: 4px; margin-bottom: 6px; }}
        pre {{ background-color: {code_bg}; font-family: Consolas, 'Cascadia Mono', monospace; padding: 6px; }}
        code {{ background-color: {code_bg}; font-family: Consolas, 'Cascadia Mono', monospace; }}
        table {{ border-color: {border}; border-collapse: collapse; margin-top: 6px; margin-bottom: 6px; }}
        th {{ background-color: {code_bg}; font-weight: 600; }}
        a {{ color: {link}; }}
        h1 {{ font-size: 150%; }} h2 {{ font-size: 130%; }} h3 {{ font-size: 115%; }}
    """


def blocked_resource(_url: QUrl):
    """Aucune ressource externe ou locale n'est chargée dans les réponses."""
    return None
