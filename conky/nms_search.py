#!/usr/bin/env python3
"""Inventory search for the right-hand conky screen.

    nms_search.py                 ask for a search term (KDE dialog)
    nms_search.py copper          search for "copper"
    nms_search.py --clear         back to the usual inventory panel
    nms_search.py --watch         click handler, started by right.conf

The screen shows whatever search is in the state file, so all of these just
write it; the panel picks it up on its next refresh.

Why a separate click handler: conky 1.22's own mouse hook never sees button
presses under XInput2 (it resolves the window under the pointer with the
wrong device id, then drops the duplicate event as already handled; motion
happens to arrive in the other order and works). So this watches raw button
events on the root window, which X hands to every client that asks, and acts
when the window under the pointer is the bases screen: left-click to search,
right-click to clear. Standard library only - Xlib and libXi through ctypes.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "nms-conky-search.json"
WINDOW_CLASS = b"nms-conky-right"


def set_query(query: str | None) -> None:
    query = (query or "").strip()
    tmp = STATE.with_name(f"{STATE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"query": query, "at": time.time()}))
    tmp.replace(STATE)


def current() -> str:
    try:
        return json.loads(STATE.read_text()).get("query", "")
    except (OSError, ValueError):
        return ""


def prompt() -> None:
    """Ask for a term. Cancel leaves things as they are; empty clears."""
    try:
        r = subprocess.run(["kdialog", "--title", "No Man's Sky", "--inputbox",
                            "Find in inventory (part of a name, empty to clear):", current()],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return
    if r.returncode == 0:
        set_query(r.stdout)


# ------------------------------------------------------------ click watcher --

class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", ctypes.c_int), ("mask_len", ctypes.c_int),
                ("mask", ctypes.POINTER(ctypes.c_ubyte))]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("cookie", ctypes.c_uint), ("data", ctypes.c_void_p)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xcookie", XGenericEventCookie), ("pad", ctypes.c_long * 24)]


class XIRawEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("time", ctypes.c_ulong), ("deviceid", ctypes.c_int), ("sourceid", ctypes.c_int),
                ("detail", ctypes.c_int), ("flags", ctypes.c_int)]


class XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


GENERIC_EVENT = 35
XI_RAW_BUTTON_PRESS = 15
XI_ALL_MASTER_DEVICES = 1


def _lib(name: str):
    path = ctypes.util.find_library(name)
    if not path:
        raise OSError(f"lib{name} not found")
    return ctypes.CDLL(path)


def _conky_running() -> bool:
    """Is a conky running right.conf from this directory? Checked by command
    line rather than pid, because `conky -d` forks after reading its config."""
    conf = str(Path(__file__).resolve().with_name("right.conf")).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == b"conky" and any(
                a == conf or a.endswith(b"/right.conf") and Path(a.decode(errors="replace")).resolve() == Path(conf.decode())
                for a in argv[1:]):
            return True
    return False


def watch() -> None:
    """Run until no conky is showing the bases screen any more."""
    lock = open(STATE.with_suffix(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return                                   # another watcher has it

    x = _lib("X11")
    xi = _lib("Xi")
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XConnectionNumber.argtypes = [ctypes.c_void_p]
    x.XPending.argtypes = [ctypes.c_void_p]
    x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
    x.XGetEventData.argtypes = [ctypes.c_void_p, ctypes.POINTER(XGenericEventCookie)]
    x.XFreeEventData.argtypes = [ctypes.c_void_p, ctypes.POINTER(XGenericEventCookie)]
    x.XQueryExtension.argtypes = [ctypes.c_void_p, ctypes.c_char_p] + [ctypes.POINTER(ctypes.c_int)] * 3
    x.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.POINTER(ctypes.c_ulong)] * 2 \
        + [ctypes.POINTER(ctypes.c_int)] * 4 + [ctypes.POINTER(ctypes.c_uint)]
    x.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XClassHint)]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XFlush.argtypes = [ctypes.c_void_p]
    xi.XISelectEvents.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XIEventMask), ctypes.c_int]
    # A window that vanishes mid-query raises BadWindow; ignore it, don't exit.
    handler_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    ignore = handler_t(lambda d, e: 0)
    x.XSetErrorHandler(ignore)

    dpy = x.XOpenDisplay(None)
    if not dpy:
        return
    root = x.XDefaultRootWindow(dpy)
    opcode, ev_base, err_base = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    if not x.XQueryExtension(dpy, b"XInputExtension", ctypes.byref(opcode),
                             ctypes.byref(ev_base), ctypes.byref(err_base)):
        return
    mask = (ctypes.c_ubyte * 4)()
    mask[XI_RAW_BUTTON_PRESS >> 3] |= 1 << (XI_RAW_BUTTON_PRESS & 7)
    em = XIEventMask(XI_ALL_MASTER_DEVICES, len(mask), mask)
    xi.XISelectEvents(dpy, root, ctypes.byref(em), 1)
    x.XFlush(dpy)

    def over_screen() -> bool:
        """Is the pointer over the bases window (at any depth)?"""
        win = root
        for _ in range(8):
            r, child = ctypes.c_ulong(), ctypes.c_ulong()
            ints = [ctypes.c_int() for _ in range(4)]
            m = ctypes.c_uint()
            if not x.XQueryPointer(dpy, win, ctypes.byref(r), ctypes.byref(child),
                                   *[ctypes.byref(i) for i in ints], ctypes.byref(m)):
                return False
            if not child.value:
                return False
            hint = XClassHint()
            if x.XGetClassHint(dpy, child.value, ctypes.byref(hint)):
                names = [ctypes.string_at(p) for p in (hint.res_name, hint.res_class) if p]
                for p in (hint.res_name, hint.res_class):
                    if p:
                        x.XFree(p)
                if WINDOW_CLASS in names:
                    return True
            win = child.value
        return False

    fd = x.XConnectionNumber(dpy)
    ev = XEvent()
    dialog = None
    while _conky_running():
        select.select([fd], [], [], 5.0)
        while x.XPending(dpy):
            x.XNextEvent(dpy, ctypes.byref(ev))
            if ev.type != GENERIC_EVENT or ev.xcookie.extension != opcode.value:
                continue
            if not x.XGetEventData(dpy, ctypes.byref(ev.xcookie)):
                continue
            try:
                if ev.xcookie.evtype != XI_RAW_BUTTON_PRESS:
                    continue
                button = ctypes.cast(ev.xcookie.data, ctypes.POINTER(XIRawEvent)).contents.detail
            finally:
                x.XFreeEventData(dpy, ctypes.byref(ev.xcookie))
            if button not in (1, 3) or not over_screen():
                continue
            if button == 3:
                set_query("")
            elif dialog is None or dialog.poll() is not None:
                dialog = subprocess.Popen([sys.executable, __file__],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--watch":
        watch()
    elif len(argv) >= 2 and argv[1] == "--clear":
        set_query("")
    elif len(argv) >= 2:
        set_query(" ".join(argv[1:]))
    else:
        prompt()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
