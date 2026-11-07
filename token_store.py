"""Small token-at-rest helper using Windows DPAPI for per-user encryption."""
from __future__ import annotations

import base64
import ctypes
import os
import tempfile
from pathlib import Path

_PREFIX = b"A-BEATS-DPAPI-1\0"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def is_protected(data: bytes) -> bool:
    return data.startswith(_PREFIX)


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI доступен только в Windows.")
    crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DataBlob)]
    else:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DataBlob),
                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DataBlob)]
    function.restype = ctypes.c_int
    ok = function(ctypes.byref(source), "A-BEATS OAuth token" if protect else None, None,
                  None, None, flags, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    """Encrypt on Windows; preserve raw bytes on non-Windows development hosts."""
    if os.name != "nt":
        return data
    encrypted = _dpapi(data, protect=True)
    return _PREFIX + base64.b64encode(encrypted)


def unprotect(data: bytes) -> bytes:
    if not is_protected(data):
        return data  # backwards compatibility with pre-DPAPI token files
    if os.name != "nt":
        raise RuntimeError("Этот OAuth-токен зашифрован Windows DPAPI и может быть открыт только в том же профиле Windows.")
    try:
        encrypted = base64.b64decode(data[len(_PREFIX):], validate=True)
    except Exception as exc:
        raise ValueError("Файл OAuth-токена повреждён.") from exc
    return _dpapi(encrypted, protect=False)


def write_token(path: str | Path, data: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = protect(data)
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
