"""Relais du raccourci, lancé avec les droits administrateur (sans Qt, démarrage rapide).

Pourquoi : un jeu lancé en administrateur (League of Legends avec Vanguard…) ne laisse pas ses touches
parvenir à un programme sans ces droits. Le relais, élevé, surveille la touche par trois méthodes
(voir touches.py) et écrit « HOTKEY <méthode> » dans le tube nommé ouvert par l'appli principale,
qui reste normale (glisser-déposer intact). Il s'arrête dès que l'appli ferme le tube ou se termine.
Journal : %TEMP%\\AssistantPC-relais.log

Usage : AssistantPC.exe --relais-raccourci <modificateurs> <touche> <tube> <pid de l'appli>
"""
import ctypes
import msvcrt
import os
import tempfile
import time
from ctypes import wintypes

from .touches import VK_XBUTTON1, VK_XBUTTON2, Watcher, is_admin

WM_HOTKEY, WM_TIMER = 0x0312, 0x0113
MOD_NOREPEAT = 0x4000
SYNCHRONIZE = 0x00100000
LOG = os.path.join(tempfile.gettempdir(), "AssistantPC-relais.log")


def log(text: str):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
    except OSError:
        pass


def main(args: list[str]) -> int:
    mods, vk, pipe, parent_pid = int(args[0]), int(args[1]), args[2], int(args[3])
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p]
    try:
        open(LOG, "w").close()
    except OSError:
        pass
    log(f"démarrage : admin={is_admin()} mods={mods} touche={vk} appli={parent_pid}")

    f = None
    for _ in range(50):  # l'appli attend la connexion
        try:
            f = open(r"\\.\pipe" + "\\" + pipe, "r+b", buffering=0)
            break
        except OSError as e:
            last = e
            time.sleep(0.1)
    if f is None:
        log(f"tube inaccessible : {last}")
        return 2

    def send(line: str) -> bool:
        try:
            f.write((line + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

    def fire(source: str):
        log(f"appui vu par : {source}")
        send(f"HOTKEY {source}")

    mouse = vk in (VK_XBUTTON1, VK_XBUTTON2)
    hotkey_ok = (not mouse) and bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
    watcher = Watcher(mods, vk, fire)
    log(f"raccourci Windows : {hotkey_ok} · crochet : {watcher.hook_ok}")
    send(f"OK admin={int(is_admin())} raccourci={int(hotkey_ok)} crochet={int(watcher.hook_ok)}")

    parent = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
    handle = msvcrt.get_osfhandle(f.fileno())
    user32.SetTimer(None, 0, 30, None)
    msg = wintypes.MSG()
    ticks = 0
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                watcher.fire("raccourci")
            elif msg.message == WM_TIMER:
                watcher.poll()
                ticks += 1
                if ticks % 33 == 0:  # ~1 s
                    if parent and kernel32.WaitForSingleObject(parent, 0) == 0:
                        log("appli terminée")
                        break
                    if not kernel32.PeekNamedPipe(handle, None, 0, None, None, None):
                        log("tube fermé par l'appli")
                        break
            else:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        watcher.close()
        if hotkey_ok:
            user32.UnregisterHotKey(None, 1)
        try:
            f.close()
        except OSError:
            pass
        log("arrêt")
    return 0
