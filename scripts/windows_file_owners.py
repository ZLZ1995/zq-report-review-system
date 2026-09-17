"""Inspect owners of explicit files; never stop/restart an application.

Uses Microsoft's Restart Manager query API. An empty result does not rule out
transient filesystem filters or directory handles outside its coverage.
"""
import ctypes as c
import os
from ctypes import wintypes as w
from pathlib import Path


def file_owners(paths):
    if os.name != 'nt':
        raise OSError('Windows Restart Manager is required')
    names = [str(Path(path).resolve(strict=True)) for path in paths]
    if not names or len(names) > 100 or any(not Path(name).is_file() for name in names):
        raise ValueError('Supply 1 to 100 existing files, not directories')

    class Process(c.Structure):
        _fields_ = [('pid', w.DWORD), ('started', w.FILETIME)]

    class Info(c.Structure):
        _fields_ = [('process', Process), ('name', w.WCHAR * 256),
                    ('service', w.WCHAR * 64), ('kind', c.c_int),
                    ('status', w.ULONG), ('session', w.DWORD), ('restartable', w.BOOL)]

    api = c.WinDLL('Rstrtmgr.dll')
    api.RmStartSession.argtypes = [c.POINTER(w.DWORD), w.DWORD, w.LPWSTR]
    api.RmRegisterResources.argtypes = [w.DWORD, w.UINT, c.POINTER(w.LPCWSTR),
                                        w.UINT, c.POINTER(Process), w.UINT, c.POINTER(w.LPCWSTR)]
    api.RmGetList.argtypes = [w.DWORD, c.POINTER(w.UINT), c.POINTER(w.UINT),
                              c.POINTER(Info), c.POINTER(w.DWORD)]
    api.RmEndSession.argtypes = [w.DWORD]
    for name in ('RmStartSession', 'RmRegisterResources', 'RmGetList', 'RmEndSession'):
        getattr(api, name).restype = w.DWORD
    handle = w.DWORD()

    def check(code):
        if code:
            raise OSError(code, 'Restart Manager query failed')

    check(api.RmStartSession(c.byref(handle), 0, c.create_unicode_buffer(33)))
    try:
        check(api.RmRegisterResources(handle, len(names), (w.LPCWSTR * len(names))(*names),
                                      0, None, 0, None))
        needed, count, reasons = w.UINT(), w.UINT(), w.DWORD()
        code = api.RmGetList(handle, c.byref(needed), c.byref(count), None, c.byref(reasons))
        if code == 0:
            return []
        if code != 234:
            check(code)
        if needed.value > 1024:
            raise ValueError('Too many owners for bounded diagnostic')
        count.value = needed.value
        entries = (Info * count.value)()
        check(api.RmGetList(handle, c.byref(needed), c.byref(count), entries, c.byref(reasons)))
        return [{'pid': entry.process.pid, 'name': entry.name, 'service': entry.service}
                for entry in entries[:count.value]]
    finally:
        api.RmEndSession(handle)
