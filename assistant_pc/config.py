"""Réglages de l'appli, dans %APPDATA%\\AssistantPC\\config.json. Jamais de mot de passe ni de jeton ici."""
import json
import os
import sys
from pathlib import Path

APP_NAME = "AssistantPC"
VERSION = "0.3.1"

DEFAULT_URL = "https://192.168.1.41:8443"
DEFAULT_FINGERPRINT = "18:28:CD:69:F6:71:DA:A7:5E:9A:39:B9:F1:65:C1:9F:3E:84:72:EF:52:02:CA:69:83:75:4E:6C:D8:C9:1B:32"
DEFAULT_MODEL = "qwen3.8"

DEFAULTS = {
    "server_url": DEFAULT_URL,
    "fingerprint": DEFAULT_FINGERPRINT,
    "username": "",
    "model": DEFAULT_MODEL,
    "think_level": None,  # None = réglage du serveur, sinon 0 à 3
    "web": False,
    "instructions": "",
    "hotkey": "Ctrl+Alt+Space",
    "edge_button": True,
    "edge_side": "right",
    "edge_y": 0.4,
    "always_on_top": False,
    "start_with_windows": False,
    "auto_update": True,  # vérifie les Releases GitHub au démarrage
    "geometry": None,
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.path.expanduser("~/.config")
    d = Path(base or ".") / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = config_dir() / "config.json"
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def normalize_fingerprint(text: str) -> str:
    """« 18:28:cd… », « 1828CD… » ou avec espaces → « 18:28:CD:… » ; chaîne vide si invalide."""
    hexa = "".join(c for c in text if c not in ": \t\n").upper()
    if len(hexa) != 64 or any(c not in "0123456789ABCDEF" for c in hexa):
        return ""
    return ":".join(hexa[i:i + 2] for i in range(0, 64, 2))


def set_start_with_windows(enabled: bool) -> str | None:
    """Ajoute ou retire l'appli du démarrage de Windows (HKCU\\…\\Run). Renvoie un message d'erreur éventuel."""
    if sys.platform != "win32":
        return "Disponible seulement sous Windows"
    if not getattr(sys, "frozen", False):
        return "Disponible seulement avec le .exe"
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --cache')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError as e:
        return f"Registre inaccessible : {e}"
    return None
