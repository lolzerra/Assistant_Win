"""Exécute un appel réseau dans un fil à part et rend le résultat au fil de l'interface (signaux Qt)."""
import threading
import traceback

from PySide6.QtCore import QObject, Signal

_alive: set = set()  # garde les tâches en vie jusqu'à leur fin


class Task(QObject):
    ok = Signal(object)
    err = Signal(object)


def run(fn, on_ok=None, on_err=None):
    task = Task()
    _alive.add(task)

    def done():
        _alive.discard(task)

    if on_ok:
        task.ok.connect(on_ok)
    if on_err:
        task.err.connect(on_err)
    task.ok.connect(done)
    task.err.connect(done)

    def body():
        try:
            result = fn()
        except Exception as e:  # remis à l'interface, qui l'affiche
            traceback.print_exc()
            task.err.emit(e)
        else:
            task.ok.emit(result)

    threading.Thread(target=body, daemon=True).start()
    return task


def message(e: Exception) -> str:
    from ..api import ApiError
    if isinstance(e, ApiError):
        return str(e)
    return f"Erreur inattendue : {e}"
