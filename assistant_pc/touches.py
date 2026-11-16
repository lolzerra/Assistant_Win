"""Détection d'une touche ou d'un bouton de souris sans Qt (utilisé par le relais et par l'appli).

Trois méthodes, la première qui voit l'appui déclenche (les doublons rapprochés sont ignorés) :
- RegisterHotKey : le raccourci Windows classique (touches seulement) ;
- crochet bas niveau (WH_KEYBOARD_LL / WH_MOUSE_LL) : appelé avant le jeu s'il est installé après lui ;
- scrutation de GetAsyncKeyState toutes les 30 ms.
"""
import ctypes
import time
from ctypes import wintypes

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_XBUTTON1, VK_XBUTTON2 = 0x05, 0x06
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
MOUSE = {"Souris 4": VK_XBUTTON1, "Souris 5": VK_XBUTTON2}  # boutons latéraux arrière / avant

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP = 0x100, 0x104, 0x101, 0x105
WM_XBUTTONDOWN = 0x020B

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def _user32():
    u = ctypes.windll.user32
    u.SetWindowsHookExW.restype = ctypes.c_void_p
    u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
    u.CallNextHookEx.restype = ctypes.c_ssize_t
    u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    u.GetAsyncKeyState.restype = ctypes.c_short
    return u


class Watcher:
    """Surveille une combinaison (modificateurs + code de touche, ou bouton de souris) ; appelle fire(source)."""

    def __init__(self, mods: int, vk: int, fire, use_hook=True):
        self.mods, self.vk, self._fire = mods, vk, fire
        self.mouse = vk in (VK_XBUTTON1, VK_XBUTTON2)
        self.u = _user32()
        self.last = 0.0
        self.was_down = False
        self.hook = None
        self._proc = None  # garder la fonction en vie
        self.hook_ok = False
        if use_hook:
            self._install_hook()

    def mods_ok(self) -> bool:
        down = lambda vk: bool(self.u.GetAsyncKeyState(vk) & 0x8000)
        if self.mods & MOD_CONTROL and not down(VK_CONTROL):
            return False
        if self.mods & MOD_ALT and not down(VK_MENU):
            return False
        if self.mods & MOD_SHIFT and not down(VK_SHIFT):
            return False
        if self.mods & MOD_WIN and not (down(VK_LWIN) or down(VK_RWIN)):
            return False
        return True

    def fire(self, source: str):
        now = time.monotonic()
        if now - self.last < 0.4:  # même appui vu par plusieurs méthodes
            return
        self.last = now
        self._fire(source)

    # Crochet bas niveau
    def _install_hook(self):
        def proc(code, wparam, lparam):
            try:
                if code == 0:
                    if self.mouse and wparam == WM_XBUTTONDOWN:
                        btn = (MSLLHOOKSTRUCT.from_address(lparam).mouseData >> 16) & 0xFFFF
                        if (btn == 1 and self.vk == VK_XBUTTON1) or (btn == 2 and self.vk == VK_XBUTTON2):
                            self.fire("crochet")
                    elif not self.mouse and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        if KBDLLHOOKSTRUCT.from_address(lparam).vkCode == self.vk and self.mods_ok():
                            self.fire("crochet")
            except Exception:
                pass
            return self.u.CallNextHookEx(None, code, wparam, lparam)

        self._proc = HOOKPROC(proc)
        module = ctypes.windll.kernel32.GetModuleHandleW(None)
        self.hook = self.u.SetWindowsHookExW(WH_MOUSE_LL if self.mouse else WH_KEYBOARD_LL, self._proc,
                                             module, 0)
        self.hook_ok = bool(self.hook)

    # Scrutation (à appeler toutes les ~30 ms)
    def poll(self):
        down = bool(self.u.GetAsyncKeyState(self.vk) & 0x8000)
        if down and not self.was_down and self.mods_ok():
            self.fire("scrutation")
        self.was_down = down

    def close(self):
        if self.hook:
            self.u.UnhookWindowsHookEx(self.hook)
            self.hook = None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
