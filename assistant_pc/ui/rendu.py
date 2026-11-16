"""Markdown → HTML pour QTextBrowser (tableaux, listes, code). Le HTML brut du modèle est affiché comme du texte."""
import html as htmlmod
import re

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


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)[^`]*$")


def split_code(text: str) -> list[tuple]:
    """Découpe le Markdown en morceaux : ("text", markdown) et ("code", code, langage, fermé).
    Un bloc encore ouvert (réponse en cours) est rendu comme un bloc de code."""
    parts: list[tuple] = []
    buf: list[str] = []
    code: list[str] | None = None
    fence, lang = "", ""
    for line in text.split("\n"):
        if code is None:
            m = _FENCE.match(line)
            if m:
                if buf:
                    parts.append(("text", "\n".join(buf)))
                    buf = []
                fence, lang, code = m.group(1), m.group(2), []
            else:
                buf.append(line)
        else:
            stripped = line.strip()
            if stripped.startswith(fence[0] * len(fence)) and set(stripped) == {fence[0]}:
                parts.append(("code", "\n".join(code), lang, True))
                code = None
            else:
                code.append(line)
    if code is not None:
        parts.append(("code", "\n".join(code), lang, False))
    elif buf:
        parts.append(("text", "\n".join(buf)))
    return [p for p in parts if p[0] == "code" or p[1].strip()]
