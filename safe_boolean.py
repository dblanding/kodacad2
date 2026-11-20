"""
safe_boolean.py -- Fuse / Cut / Common with guard rails (Session 181).

Doug fused four 8 in round bars (equal diameters, crossing axes -- a
degenerate intersection for OCCT) and the Boolean ran away: minutes of
nothing, then swapping, then the whole laptop froze. A Boolean in the
application's own process can neither be watched nor stopped. Here it
runs in a worker process (boolean_worker.py) that the application
SUPERVISES:

  * a busy box with elapsed time and the worker's memory use, and a
    Cancel button (the window stays alive: the supervisor loop pumps
    Qt events);
  * a time limit (TIMEOUT s) and a memory limit (a fraction of the
    machine's RAM, MEM_FRACTION) -- when either is exceeded the worker
    is killed and the caller gets a plain message; nothing is changed;
  * a crash of OCCT kills only the worker.

    shape, msg = safe_boolean.run_boolean("fuse", a, b, parent=win)
    # shape None + msg on any failure; msg "" on success

Shapes travel as BREP files (locations are kept; XDE colours / names live
in the document, not the shape). `supervise()` is the pure subprocess
part (no Qt, no OCP) and is what the offline tests exercise.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

TIMEOUT = 180.0           # seconds; a Boolean that takes longer is stopped
MEM_FRACTION = 0.5        # of physical RAM, for the WORKER process
MEM_MIN_MB = 1024         # never smaller than this
POLL = 0.05               # supervisor poll interval, seconds

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "boolean_worker.py")

_VERBS = {"fuse": "Fuse", "cut": "Subtract", "common": "Common"}


def mem_limit_bytes():
    """The worker's memory ceiling: MEM_FRACTION of physical RAM (at
    least MEM_MIN_MB). Falls back to 4 GiB when RAM cannot be read."""
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        total = 8 * 1024 ** 3
    return max(int(total * MEM_FRACTION), MEM_MIN_MB * 1024 ** 2)


def rss_bytes(pid):
    """Resident memory of process `pid` (Linux /proc), or None."""
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def supervise(cmd, timeout, mem_limit, cancelled=None, tick=None,
              stdout_path=None, stderr_path=None):
    """Run `cmd` as a child process and watch it. Every POLL seconds:
    call tick(elapsed_s, rss_bytes_or_None) (the GUI pumps events
    there), stop on cancelled() -> True, on time over `timeout`, on
    resident memory over `mem_limit`. Returns (status, returncode)
    with status one of 'ok' (exit 0), 'crashed' (non-zero exit),
    'timeout', 'memory', 'cancelled'. Raises OSError if the process
    cannot be started. The child's stdout / stderr go to the given
    files (pipes could fill up and deadlock the child)."""
    out = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
    err = open(stderr_path, "wb") if stderr_path else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err)
    finally:
        for f in (out, err):
            if f is not subprocess.DEVNULL:
                f.close()
    t0 = time.monotonic()
    status = None
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                status = "ok" if rc == 0 else "crashed"
                break
            elapsed = time.monotonic() - t0
            rss = rss_bytes(proc.pid)
            if tick is not None:
                tick(elapsed, rss)
            if cancelled is not None and cancelled():
                status = "cancelled"
            elif elapsed > timeout:
                status = "timeout"
            elif rss is not None and rss > mem_limit:
                status = "memory"
            if status:
                break
            time.sleep(POLL)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return status, proc.returncode


def _describe_stop(status, verb, timeout, mem_limit):
    if status == "timeout":
        return (f"{verb} was stopped after {timeout:.0f} s -- it was "
                f"taking too long. Nothing was changed. Equal-diameter "
                f"round parts with crossing axes, or surfaces that only "
                f"just touch, are the usual cause: change a diameter "
                f"slightly, or overlap the parts a little more.")
    if status == "memory":
        return (f"{verb} was stopped: it was using more than "
                f"{mem_limit / 1024 ** 3:.1f} GB of memory. Nothing was "
                f"changed. Equal-diameter round parts with crossing "
                f"axes, or surfaces that only just touch, are the "
                f"usual cause: change a diameter slightly, or overlap "
                f"the parts a little more.")
    if status == "cancelled":
        return f"{verb} cancelled. Nothing was changed."
    return ""


def run_boolean(op, a, b, parent=None, timeout=None, mem_limit=None,
                label=None):
    """A `op` B ('fuse' | 'cut' | 'common') in a supervised worker.
    Returns (shape, "") on success, (None, message) otherwise.
    `parent` (a QWidget) hosts the busy box; without a running
    QApplication there is no box (the limits still apply)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    verb = _VERBS.get(op, op)
    timeout = TIMEOUT if timeout is None else timeout
    mem_limit = mem_limit_bytes() if mem_limit is None else mem_limit
    box = _BusyBox(parent, label or f"{verb} in progress...") \
        if parent is not None else None
    try:
        with tempfile.TemporaryDirectory(prefix="kodacad_bool_") as td:
            pa, pb, po = (os.path.join(td, n) for n in
                          ("a.brep", "b.brep", "out.brep"))
            BRepTools.Write_s(a, pa)
            BRepTools.Write_s(b, pb)
            cmd = [sys.executable, "-I", WORKER, op, pa, pb, po]
            so, se = os.path.join(td, "out.txt"), os.path.join(td, "err.txt")
            try:
                status, rc = supervise(
                    cmd, timeout, mem_limit,
                    cancelled=(box.cancelled if box else None),
                    tick=(box.tick if box else None),
                    stdout_path=so, stderr_path=se)
            except OSError as e:
                return None, f"{verb} could not be started: {e}"
            if status != "ok":
                if status == "crashed":
                    tail = ""
                    try:
                        with open(se, errors="replace") as f:
                            tail = f.read().strip().splitlines()[-6:]
                    except OSError:
                        pass
                    print(f"[safe_boolean] worker died, exit code {rc}; "
                          f"stderr tail: {tail}")
                    return None, (f"{verb} crashed inside OpenCascade "
                                  f"(the application is fine and nothing "
                                  f"was changed).")
                print(f"[safe_boolean] {op} stopped: {status}")
                return None, _describe_stop(status, verb, timeout,
                                            mem_limit)
            try:
                with open(so) as f:
                    info = json.loads(f.read().strip().splitlines()[-1])
            except Exception:
                return None, f"{verb}: the worker gave no answer."
            if not info.get("done") or info.get("null"):
                return None, (f"{verb} failed -- the parts could not be "
                              f"combined.")
            result = TopoDS_Shape()
            if not BRepTools.Read_s(result, po, BRep_Builder()) \
                    or result.IsNull():
                return None, f"{verb}: could not read the worker's result."
            return result, ""
    finally:
        if box is not None:
            box.close()


class _BusyBox:
    """Busy indicator with Cancel, shown only if the operation takes
    more than half a second. Qt imported lazily (no Qt for the tests)."""

    def __init__(self, parent, text):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QProgressDialog
        self._text = text
        self._dlg = QProgressDialog(text, "Cancel", 0, 0, parent)
        self._dlg.setWindowTitle("Working")
        self._dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._dlg.setMinimumDuration(500)
        self._dlg.setAutoClose(False)
        self._dlg.setAutoReset(False)

    def tick(self, elapsed, rss):
        from PySide6.QtWidgets import QApplication
        mem = f", {rss / 1024 ** 2:.0f} MB" if rss else ""
        self._dlg.setLabelText(f"{self._text}\n{elapsed:.0f} s{mem}")
        QApplication.processEvents()

    def cancelled(self):
        return self._dlg.wasCanceled()

    def close(self):
        try:
            self._dlg.reset()
            self._dlg.close()
        except Exception:
            pass
