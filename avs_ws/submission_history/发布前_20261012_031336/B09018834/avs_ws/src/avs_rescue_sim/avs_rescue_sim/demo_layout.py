"""Best-effort, one-time placement of this launch's native simulator windows.

The caller supplies exact process IDs and calls ``poll()`` from its GUI timer.
Only managed top-level clients (or direct root children on a display without a
window manager) are considered. No title matching, process search, or recursive
window-tree search is used, so another launch and Gazebo's render child are safe.
"""

import ctypes
import ctypes.util
import os
import re
import shutil
import subprocess
import time
import warnings


class _ClientData(ctypes.Union):
    _fields_ = [('b', ctypes.c_char * 20), ('s', ctypes.c_short * 10),
                ('l', ctypes.c_long * 5)]


class _ClientMessage(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong),
                ('send_event', ctypes.c_int), ('display', ctypes.c_void_p),
                ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', _ClientData)]


class _Event(ctypes.Union):
    _fields_ = [('client', _ClientMessage), ('pad', ctypes.c_long * 24)]


class _X11:
    """Small Xlib wrapper; errors from windows closed during placement are benign."""

    def __init__(self):
        library = ctypes.util.find_library('X11')
        if not library:
            raise RuntimeError('libX11 is unavailable')
        self.lib = ctypes.CDLL(library)
        signatures = {
            'XOpenDisplay': ([ctypes.c_char_p], ctypes.c_void_p),
            'XDefaultRootWindow': ([ctypes.c_void_p], ctypes.c_ulong),
            'XInternAtom': ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_ulong),
            'XSendEvent': ([ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                            ctypes.c_long, ctypes.POINTER(_Event)], ctypes.c_int),
            'XMoveResizeWindow': ([ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint, ctypes.c_uint], ctypes.c_int),
            'XSync': ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            'XCloseDisplay': ([ctypes.c_void_p], ctypes.c_int),
            'XSetErrorHandler': ([ctypes.c_void_p], ctypes.c_void_p),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes = arguments
            function.restype = result
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Cannot connect to the X11 display')
        self.root = self.lib.XDefaultRootWindow(self.display)
        self.atoms = {}
        self.error = False
        self._error_callback = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(self._on_error)

    def _on_error(self, _display, _event):
        self.error = True
        return 0

    def atom(self, name):
        if name not in self.atoms:
            self.atoms[name] = self.lib.XInternAtom(self.display, name.encode(), False)
        return self.atoms[name]

    def message(self, window, kind, values):
        event = _Event()
        event.client.type = 33  # ClientMessage
        event.client.display = self.display
        event.client.window = window
        event.client.message_type = self.atom(kind)
        event.client.format = 32
        for index, value in enumerate(values):
            event.client.data.l[index] = value
        # EWMH requests are sent to the root, not directly to the managed client.
        return self.lib.XSendEvent(self.display, self.root, False,
                                   (1 << 19) | (1 << 20), ctypes.byref(event))

    def place(self, window, rectangle, managed, frame):
        x, y, width, height = rectangle
        left, right, top, bottom = frame
        width, height = max(1, width - left - right), max(1, height - top - bottom)
        self.error = False
        # Xlib's error handler is process-global. Restore the previous handler
        # immediately after this connection's requests have been synchronized.
        previous = self.lib.XSetErrorHandler(ctypes.cast(self._error_callback, ctypes.c_void_p))
        try:
            if managed:
                self.message(window, '_NET_WM_STATE', [
                    0, self.atom('_NET_WM_STATE_MAXIMIZED_VERT'),
                    self.atom('_NET_WM_STATE_MAXIMIZED_HORZ'), 1, 0])
                self.message(window, '_NET_WM_STATE', [
                    0, self.atom('_NET_WM_STATE_FULLSCREEN'), 0, 1, 0])
                # NorthWestGravity + all geometry fields + application source.
                sent = self.message(window, '_NET_MOVERESIZE_WINDOW',
                                    [1 | (15 << 8) | (1 << 12), x, y, width, height])
            else:
                sent = self.lib.XMoveResizeWindow(self.display, window, x, y, width, height)
            self.lib.XSync(self.display, False)
            return bool(sent) and not self.error
        finally:
            self.lib.XSetErrorHandler(previous)

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None


def _rectangle(value):
    """Accept a QRect without importing Qt, or an (x, y, width, height) tuple."""
    if hasattr(value, 'getRect'):
        value = value.getRect()
    x, y, width, height = map(int, value)
    if width <= 0 or height <= 0:
        raise ValueError('Window slot must have positive width and height')
    return x, y, width, height


class NativeWindowLayout:
    """Place ``gazebo`` and ``rviz`` once, using their explicitly supplied PIDs.

    ``pids`` maps either supported key to its launch process PID. ``rectangles``
    maps the same keys to QRects or ``(x, y, width, height)`` screen coordinates.
    Call ``poll()`` every 300–500 ms until it returns True, and call ``close()``
    when the viewer closes. Missing/zero PIDs are skipped. Failure only emits a
    warning; simulation and manual window placement remain available.
    """

    def __init__(self, pids, rectangles, timeout=30.0):
        self.pending = {name: (int(pids[name]), _rectangle(rectangles[name]))
                        for name in ('gazebo', 'rviz')
                        if name in pids and name in rectangles and int(pids[name] or 0) > 0}
        self.placed = {}
        self.deadline = time.monotonic() + max(0.0, float(timeout))
        self.next_poll = 0.0
        self._x11 = None
        self._closed = False
        self._warned = False
        # xprop emits fixed English property names; xwininfo labels are parsed.
        self._environment = dict(os.environ, LC_ALL='C')
        if not self.pending:
            self.close()
        elif not os.environ.get('DISPLAY') or not all(shutil.which(tool) for tool in ('xprop', 'xwininfo')):
            self._finish('X11 tools/display unavailable; arrange Gazebo and RViz manually')
        else:
            try:
                self._x11 = _X11()
            except (OSError, RuntimeError) as exc:
                self._finish(str(exc))

    def _finish(self, message):
        if not self._warned:
            warnings.warn('AVS window layout: ' + message, RuntimeWarning, stacklevel=2)
            self._warned = True
        self.close()

    def _run(self, *command):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return ''
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=min(0.5, remaining), env=self._environment)
            return result.stdout if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            return ''

    def _windows(self):
        properties = self._run('xprop', '-root', '_NET_CLIENT_LIST', '_NET_SUPPORTING_WM_CHECK')
        clients = re.search(r'^_NET_CLIENT_LIST\(WINDOW\):.*$', properties, re.MULTILINE)
        if clients:
            return [int(value, 16) for value in re.findall(r'0x[0-9a-fA-F]+', clients.group())], True
        if re.search(r'_NET_SUPPORTING_WM_CHECK\(WINDOW\):.*0x[1-9a-fA-F]', properties):
            # Do not mistake window-manager frame windows for actual clients.
            return [], True
        tree = self._run('xwininfo', '-root', '-children')
        # -children is deliberately nonrecursive: a Gazebo render widget must
        # never be mistaken for the main window, even if it carries the PID.
        return [int(value, 16) for value in re.findall(r'^\s+(0x[0-9a-fA-F]+)\s', tree, re.MULTILINE)], False

    def poll(self):
        """Try ready windows once; return True when finished or timed out."""
        if self._closed:
            return True
        now = time.monotonic()
        if now >= self.deadline:
            self._finish('Timed out locating ' + ', '.join(self.pending) + '; arrange them manually')
            return True
        if now < self.next_poll:
            return False
        self.next_poll = now + 0.35
        windows, managed = self._windows()
        for window in windows:
            if time.monotonic() >= self.deadline:
                break
            properties = self._run('xprop', '-id', hex(window), '_NET_WM_PID',
                                   '_NET_WM_WINDOW_TYPE', '_NET_FRAME_EXTENTS')
            owner = re.search(r'_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)', properties)
            if not owner:
                continue
            matching = [name for name, (pid, _) in self.pending.items() if pid == int(owner.group(1))]
            if not matching:
                continue
            kind = re.search(r'_NET_WM_WINDOW_TYPE\(ATOM\)\s*=\s*(.*)', properties)
            if kind and '_NET_WM_WINDOW_TYPE_NORMAL' not in kind.group(1):
                continue
            info = self._run('xwininfo', '-id', hex(window))
            width = re.search(r'Width:\s*(\d+)', info)
            height = re.search(r'Height:\s*(\d+)', info)
            if ('IsViewable' not in info or not width or not height
                    or int(width.group(1)) < 300 or int(height.group(1)) < 200):
                continue
            extent = re.search(r'_NET_FRAME_EXTENTS\(CARDINAL\)\s*=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', properties)
            frame = tuple(map(int, extent.groups())) if extent else (0, 0, 0, 0)
            for name in matching:
                if self._x11.place(window, self.pending[name][1], managed, frame):
                    self.placed[name] = window
                    del self.pending[name]
            if not self.pending:
                self.close()
                return True
        return False

    def close(self):
        """Release X resources and make subsequent polls harmless."""
        if self._x11 is not None:
            self._x11.close()
            self._x11 = None
        self._closed = True
