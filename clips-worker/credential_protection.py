"""Wrap the local vault key using Windows account-bound DPAPI."""
import ctypes
from ctypes import wintypes


def windows_key(data: bytes, encrypt: bool) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    proc = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    proc.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    proc.restype = wintypes.BOOL
    if not proc(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('The Windows account could not unlock the local connection vault.')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)
