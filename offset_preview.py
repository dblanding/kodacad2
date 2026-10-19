"""
offset_preview.py -- Qt client for the persistent offset server
(face_offset_server.py), Session 161.

OffsetServer owns one QProcess. Everything is asynchronous: send() queues
a JSON line, replies arrive as the `message` signal (a dict), so the GUI
never blocks while OCCT works. If the server dies (a native OCCT crash,
say) `died` is emitted and the next send() starts a fresh one.
"""
import json
import os
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "face_offset_server.py")
REQUEST_TIMEOUT_MS = 90_000      # a single offset taking longer is killed


class OffsetServer(QObject):
    message = Signal(dict)
    died = Signal(str)           # reason

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._buf = b""
        self.generation = 0      # bumps on every (re)start
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(REQUEST_TIMEOUT_MS)
        self._watchdog.timeout.connect(self._on_timeout)
        self._killed_for_timeout = False

    def running(self):
        return (self._proc is not None and
                self._proc.state() != QProcess.ProcessState.NotRunning)

    def ensure_started(self):
        """True if a server is running (starting it if needed)."""
        if self.running():
            return True
        self._buf = b""
        self._killed_for_timeout = False
        p = QProcess(self)
        p.setProgram(sys.executable)
        p.setArguments(["-I", SERVER])
        p.readyReadStandardOutput.connect(self._on_stdout)
        p.readyReadStandardError.connect(self._on_stderr)
        p.finished.connect(self._on_finished)
        p.errorOccurred.connect(self._on_error)
        self._proc = p
        self.generation += 1
        p.start()
        if not p.waitForStarted(5000):
            print("[offset_preview] could not start the offset server")
            self._proc = None
            return False
        return True

    def send(self, d):
        if not self.ensure_started():
            return False
        self._proc.write((json.dumps(d) + "\n").encode("utf-8"))
        if d.get("op") == "offset":
            self._watchdog.start()
        return True

    def stop(self):
        self._watchdog.stop()
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            p.readyReadStandardOutput.disconnect(self._on_stdout)
            p.finished.disconnect(self._on_finished)
            p.errorOccurred.disconnect(self._on_error)
        except Exception:
            pass
        try:
            if p.state() != QProcess.ProcessState.NotRunning:
                p.write(b'{"op":"quit"}\n')
                if not p.waitForFinished(300):
                    p.kill()
                    p.waitForFinished(1000)
        except Exception:
            pass

    # -- internals ---------------------------------------------------
    def _on_stdout(self):
        if self._proc is None:
            return
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"{"):
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if msg.get("op") in ("offset", "error"):
                self._watchdog.stop()
            self.message.emit(msg)

    def _on_stderr(self):
        if self._proc is None:
            return
        txt = bytes(self._proc.readAllStandardError()).decode(
            "utf-8", "replace").strip()
        if txt:
            print(f"[offset server] {txt}", flush=True)

    def _on_finished(self, code, status):
        self._watchdog.stop()
        self._proc = None
        reason = ("timed out" if self._killed_for_timeout else
                  f"exit code {code}")
        print(f"[offset_preview] server ended ({reason})", flush=True)
        self.died.emit(reason)

    def _on_error(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            print("[offset_preview] server failed to start", flush=True)

    def _on_timeout(self):
        if self.running():
            self._killed_for_timeout = True
            print("[offset_preview] offset took too long; stopping server",
                  flush=True)
            self._proc.kill()
