"""Relais du raccourci, lancé avec les droits administrateur (sans Qt, démarrage rapide).

Pourquoi : un jeu lancé en administrateur (League of Legends avec Vanguard…) ne laisse pas ses touches
parvenir à un programme sans ces droits. Le relais, élevé, enregistre le raccourci et écrit « HOTKEY »
dans le tube nommé ouvert par l'appli principale, qui, elle, reste normale (glisser-déposer intact).
Il s'arrête dès que l'appli ferme le tube ou se termine.

Usage : AssistantPC.exe --relais-raccourci <modificateurs> <touche> <tube> <pid de l'appli>
"""
import ctypes
import msvcrt
import time
from ctypes import wintypes

WM_HOTKEY, WM_TIMER = 0x0312, 0x0113
MOD_NOREPEAT = 0x4000
SYNCHRONIZE = 0x00100000


def main(args: list[str]) -> int:
    mods, vk, pipe, parent_pid = int(args[0]), int(args[1]), args[2], int(args[3])
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p]

    f = None
    for _ in range(50):  # l'appli attend la connexion
        try:
            f = open(r"\\.\pipe" + "\\" + pipe, "r+b", buffering=0)
            break
        except OSError:
            time.sleep(0.1)
    if f is None:
        return 2

    def send(line: str) -> bool:
        try:
            f.write((line + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

    if not user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
        send("ERR Raccourci déjà utilisé par une autre application")
        return 1
    send("OK")

    parent = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
    handle = msvcrt.get_osfhandle(f.fileno())
    user32.SetTimer(None, 0, 1000, None)
    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if not send("HOTKEY"):
                    break
            elif msg.message == WM_TIMER:
                if parent and kernel32.WaitForSingleObject(parent, 0) == 0:
                    break  # l'appli s'est terminée
                if not kernel32.PeekNamedPipe(handle, None, 0, None, None, None):
                    break  # l'appli a fermé le tube
    finally:
        user32.UnregisterHotKey(None, 1)
        try:
            f.close()
        except OSError:
            pass
    return 0
