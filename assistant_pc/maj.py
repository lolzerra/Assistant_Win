"""Mise à jour depuis les Releases GitHub du dépôt (seule connexion hors du serveur maison).

Seuls la version et l'exe publiés sont lus ; rien n'est envoyé hormis la requête elle-même.
Remplacement : l'exe en cours est renommé en .old (Windows l'autorise), le nouveau prend sa place,
puis il est relancé et l'ancien se ferme. Le .old est supprimé au lancement suivant.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

from .config import VERSION

REPO = "lolzerra/Assistant_Win"
ASSET = "AssistantPC.exe"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


class UpdateError(Exception):
    pass


def parse(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(15, read=60), follow_redirects=True, trust_env=False,
                        headers={"User-Agent": f"AssistantPC/{VERSION}", "Accept": "application/vnd.github+json"})


def latest() -> dict:
    """{"version", "notes", "url", "size", "sha256_url", "newer"}."""
    try:
        with _client() as c:
            r = c.get(f"https://api.github.com/repos/{REPO}/releases/latest")
    except httpx.HTTPError as e:
        raise UpdateError(f"GitHub injoignable : {e.__class__.__name__}")
    if r.status_code == 404:
        raise UpdateError("Aucune version publiée.")
    if r.status_code >= 400:
        raise UpdateError(f"GitHub a répondu {r.status_code}.")
    rel = r.json()
    assets = {a["name"]: a for a in rel.get("assets", [])}
    if ASSET not in assets:
        raise UpdateError("La dernière version ne contient pas d'exe.")
    tag = rel.get("tag_name", "")
    sha = assets.get(ASSET + ".sha256")
    return {
        "version": tag.lstrip("v"),
        "notes": (rel.get("body") or "").strip(),
        "url": assets[ASSET]["browser_download_url"],
        "size": assets[ASSET]["size"],
        "sha256_url": sha["browser_download_url"] if sha else None,
        "newer": parse(tag) > parse(VERSION),
    }


def download(info: dict, progress=None, cancelled=lambda: False) -> Path:
    """Télécharge à côté de l'exe en cours (AssistantPC.exe.new) et vérifie taille et empreinte."""
    if not is_frozen():
        raise UpdateError("Mise à jour automatique possible seulement avec le .exe.")
    target = Path(sys.executable).with_name(Path(sys.executable).name + ".new")
    h = hashlib.sha256()
    done = 0
    try:
        with _client() as c:
            expected = None
            if info.get("sha256_url"):
                r = c.get(info["sha256_url"])
                if r.status_code == 200:
                    expected = r.text.split()[0].strip().lower() if r.text.strip() else None
            with c.stream("GET", info["url"]) as r:
                if r.status_code >= 400:
                    raise UpdateError(f"Téléchargement refusé ({r.status_code}).")
                with open(target, "wb") as f:
                    for chunk in r.iter_bytes(256 * 1024):
                        if cancelled():
                            raise UpdateError("Mise à jour annulée.")
                        f.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, info["size"])
    except httpx.HTTPError as e:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Téléchargement interrompu : {e.__class__.__name__}")
    except PermissionError:
        raise UpdateError(f"Impossible d'écrire dans {target.parent}.\n"
                          "Placez AssistantPC.exe dans un dossier à vous (par exemple %LOCALAPPDATA%\\AssistantPC).")
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    if done != info["size"]:
        target.unlink(missing_ok=True)
        raise UpdateError("Fichier téléchargé incomplet.")
    if expected and h.hexdigest() != expected:
        target.unlink(missing_ok=True)
        raise UpdateError("Empreinte du fichier téléchargé incorrecte : mise à jour refusée.")
    return target


def install_and_restart(new_exe: Path):
    """Remplace l'exe en cours puis lance la nouvelle version. L'appelant doit quitter juste après."""
    current = Path(sys.executable)
    old = current.with_name(current.name + ".old")
    try:
        old.unlink(missing_ok=True)
        current.rename(old)
        try:
            new_exe.rename(current)
        except OSError:
            old.rename(current)  # on remet l'ancienne version en place
            raise
    except OSError as e:
        raise UpdateError(f"Remplacement de l'exe impossible : {e.strerror or e}")
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # la nouvelle version ne doit pas réutiliser nos fichiers temporaires
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(current), "--apres-maj"], env=env, creationflags=flags, close_fds=True,
                     cwd=str(current.parent))


def cleanup():
    """Au lancement : supprime l'ancienne version laissée par une mise à jour."""
    if not is_frozen():
        return
    exe = Path(sys.executable)
    for suffix in (".old", ".new"):
        try:
            exe.with_name(exe.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass  # encore verrouillé : ce sera pour le prochain lancement
