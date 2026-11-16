"""Raccourcis clavier globaux (fonctionnent même quand l'appli n'a pas le focus, y compris en jeu).

Windows : RegisterHotKey sur une petite fenêtre native invisible ; le message WM_HOTKEY est lu par un
filtre d'événements natifs de Qt et appelle la fonction associée, dans le fil de l'interface.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_SPECIAL = {
    Qt.Key_Space: 0x20, Qt.Key_Tab: 0x09, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D, Qt.Key_Escape: 0x1B,
    Qt.Key_Backspace: 0x08, Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E, Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27,
    Qt.Key_Down: 0x28, Qt.Key_Pause: 0x13, Qt.Key_Print: 0x2C, Qt.Key_ScrollLock: 0x91,
}


def _v(enum) -> int:
    return enum.value if hasattr(enum, "value") else int(enum)


def to_native(seq: str) -> tuple[int, int] | None:
    """« Ctrl+Alt+Space » → (modificateurs, code de touche Windows), ou None si non reconnu."""
    ks = QKeySequence(seq)
    if ks.isEmpty():
        return None
    combo = ks[0]
    key, mods = _v(combo.key()), combo.keyboardModifiers()
    special = {_v(k): v for k, v in _SPECIAL.items()}
    if _v(Qt.Key_A) <= key <= _v(Qt.Key_Z) or _v(Qt.Key_0) <= key <= _v(Qt.Key_9):
        vk = key
    elif _v(Qt.Key_F1) <= key <= _v(Qt.Key_F24):
        vk = 0x70 + key - _v(Qt.Key_F1)
    elif key in special:
        vk = special[key]
    else:
        return None
    m = 0
    if mods & Qt.ControlModifier:
        m |= MOD_CONTROL
    if mods & Qt.AltModifier:
        m |= MOD_ALT
    if mods & Qt.ShiftModifier:
        m |= MOD_SHIFT
    if mods & Qt.MetaModifier:
        m |= MOD_WIN
    return m, vk


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, app):
        super().__init__()
        self._callbacks: dict[int, object] = {}
        self._names: dict[str, int] = {}
        self._next = 1
        self._host = QWidget()  # fenêtre native jamais affichée, destinataire des WM_HOTKEY
        self._hwnd = int(self._host.winId())
        if sys.platform == "win32":
            import ctypes
            self._user32 = ctypes.windll.user32
            app.installNativeEventFilter(self)

    def register(self, name: str, seq: str, callback) -> str | None:
        """(Re)définit le raccourci « name ». Renvoie un message d'erreur, ou None si tout va bien."""
        self.unregister(name)
        if not seq:
            return None
        if sys.platform != "win32":
            return "Raccourcis globaux disponibles seulement sous Windows"
        native = to_native(seq)
        if native is None:
            return f"Touche non prise en charge : {seq}"
        hid = self._next
        self._next += 1
        mods, vk = native
        if not self._user32.RegisterHotKey(self._hwnd, hid, mods | MOD_NOREPEAT, vk):
            return f"Le raccourci {seq} est déjà utilisé par une autre application"
        self._callbacks[hid] = callback
        self._names[name] = hid
        return None

    def unregister(self, name: str):
        hid = self._names.pop(name, None)
        if hid is not None:
            self._callbacks.pop(hid, None)
            if sys.platform == "win32":
                self._user32.UnregisterHotKey(self._hwnd, hid)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                cb = self._callbacks.get(int(msg.wParam))
                if cb:
                    cb()
                    return True, 0
        return False, 0


# ---------- Relais en administrateur (jeux lancés en administrateur) ----------

def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class ElevatedRelay(QObject):
    """Lance AssistantPC en administrateur avec --relais-raccourci et reçoit les appuis par un tube nommé."""
    pressed = Signal()
    state = Signal(bool, str)  # actif ?, message

    def __init__(self):
        super().__init__()
        self.server: QLocalServer | None = None
        self.conn: QLocalSocket | None = None

    def start(self, seq: str):
        self.stop()
        if sys.platform != "win32":
            self.state.emit(False, "Disponible seulement sous Windows")
            return
        native = to_native(seq)
        if native is None:
            self.state.emit(False, f"Touche non prise en charge : {seq}")
            return
        import ctypes
        import getpass
        name = f"AssistantPC-relais-{getpass.getuser()}-{os.getpid()}"
        QLocalServer.removeServer(name)
        self.server = QLocalServer()
        if not self.server.listen(name):
            self.state.emit(False, "Impossible de préparer la liaison avec le relais")
            return
        self.server.newConnection.connect(self._connected)
        args = f"--relais-raccourci {native[0]} {native[1]} {name} {os.getpid()}"
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, args
        else:
            exe = sys.executable
            params = f'"{Path(__file__).resolve().parent.parent / "run.py"}" {args}'
        # « runas » : Windows demande la confirmation administrateur (UAC).
        shell = ctypes.windll.shell32
        shell.ShellExecuteW.restype = ctypes.c_void_p
        rc = shell.ShellExecuteW(None, "runas", exe, params, None, 0)
        if (rc or 0) <= 32:
            self.stop()
            self.state.emit(False, "Droits administrateur refusés : le raccourci ne marchera pas dans les jeux "
                                   "lancés en administrateur.")
            return
        self.state.emit(False, "Démarrage du relais administrateur…")

    def _connected(self):
        self.conn = self.server.nextPendingConnection()
        if self.conn:
            self.conn.readyRead.connect(self._read)
            self.conn.disconnected.connect(lambda: self.state.emit(False, "Relais administrateur arrêté"))

    def _read(self):
        while self.conn and self.conn.canReadLine():
            line = bytes(self.conn.readLine()).decode("utf-8", "replace").strip()
            if line == "HOTKEY":
                self.pressed.emit()
            elif line == "OK":
                self.state.emit(True, "")
            elif line.startswith("ERR"):
                self.state.emit(False, line[4:])

    def stop(self):
        if self.conn is not None:
            self.conn.blockSignals(True)  # arrêt voulu : pas de message « relais arrêté »
            self.conn.abort()
            self.conn = None
        if self.server is not None:
            self.server.close()
            self.server = None
