"""Jeton du serveur dans le Gestionnaire d'identification de Windows (CredWrite, chiffré par DPAPI).

Le mot de passe n'est jamais enregistré : seul le jeton renvoyé par /api/app/login l'est.
Hors Windows (développement), le jeton reste en mémoire seulement.
"""
import sys

TARGET = "AssistantPC/jeton"
_memory: dict[str, str] = {}

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2  # reste sur ce PC, n'est pas synchronisé avec le compte Microsoft
    ERROR_NOT_FOUND = 1168

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    _advapi.CredWriteW.restype = wintypes.BOOL
    _advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    _advapi.CredReadW.restype = wintypes.BOOL
    _advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi.CredDeleteW.restype = wintypes.BOOL
    _advapi.CredFree.argtypes = [ctypes.c_void_p]
    _advapi.CredFree.restype = None


def save_token(username: str, token: str) -> bool:
    """Renvoie False si le coffre refuse (le jeton reste alors en mémoire pour cette session)."""
    _memory[TARGET] = token
    if sys.platform != "win32":
        return False
    blob = token.encode("utf-8")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = TARGET
    cred.Comment = "Jeton de l'appli Assistant PC (pas le mot de passe)"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = username or "assistant"
    return bool(_advapi.CredWriteW(ctypes.byref(cred), 0))


def load_token() -> str | None:
    if TARGET in _memory:
        return _memory[TARGET]
    if sys.platform != "win32":
        return None
    p = ctypes.POINTER(CREDENTIAL)()
    if not _advapi.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        token = bytes(c.CredentialBlob[: c.CredentialBlobSize]).decode("utf-8")
    finally:
        _advapi.CredFree(p)
    _memory[TARGET] = token
    return token


def delete_token():
    _memory.pop(TARGET, None)
    if sys.platform == "win32":
        _advapi.CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0)
