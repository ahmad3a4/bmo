"""Shared Pi camera access (rpicam-*), one user at a time."""
import contextlib
import os
import shutil
import subprocess
import threading

# Two rpicam processes at once fail with "camera in use".
_LOCK = threading.Lock()


class CameraBusy(Exception):
    pass


def has_camera() -> bool:
    return shutil.which("rpicam-still") is not None


@contextlib.contextmanager
def exclusive(timeout=15):
    """Hold the camera for longer jobs, e.g. a live preview."""
    if not _LOCK.acquire(timeout=timeout):
        raise CameraBusy()
    try:
        yield
    finally:
        _LOCK.release()


def capture(out_path, width=1024, height=768, timeout_ms=1200, label="CAMERA"):
    try:
        with exclusive():
            result = subprocess.run(
                ["rpicam-still", "-o", out_path, "--timeout", str(timeout_ms),
                 "--nopreview", "--width", str(width), "--height", str(height)],
                capture_output=True, timeout=10,
            )
    except CameraBusy:
        print(f"[{label}] Camera busy — skipped.", flush=True)
        return None
    except Exception as e:
        print(f"[{label}] Capture error: {e}", flush=True)
        return None
    if result.returncode != 0 or not os.path.exists(out_path):
        err = (result.stderr or b"").decode(errors="replace")[-300:]
        print(f"[{label}] Capture failed: {err}", flush=True)
        return None
    return out_path
