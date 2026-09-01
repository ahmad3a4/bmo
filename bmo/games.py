"""
bmo_games.py — Seamless RetroArch launcher for BMO.

When triggered:
  1. BMO's tkinter window goes full black (no desktop gap on launch)
  2. RetroArch opens fullscreen
  3. BMO's window is lowered below RetroArch (stays alive, invisible)
  4. A monitor thread watches RetroArch
  5. The moment RetroArch exits, BMO raises & redraws instantly (no gap on close)
"""

import os
import subprocess
import threading
import shutil
import time

# RetroArch binary — override via config.json "retroarch_bin"
_DEFAULT_BIN = "retroarch"


class GamesLauncher:
    """
    Manages launching RetroArch and restoring BMO display afterward.

    Usage:
        launcher = GamesLauncher(cfg, root=tk_root, bmo_faces=bmo_faces_obj)
        launcher.launch()   # called from skill thread
    """

    def __init__(self, cfg: dict, root=None, bmo_faces=None, canvas=None):
        self.bin        = cfg.get("retroarch_bin", _DEFAULT_BIN)
        self.extra_args = cfg.get("retroarch_args", [])   # e.g. ["--menu"]
        self.root       = root        # tkinter Tk root window
        self.bmo_faces  = bmo_faces   # BMOFaces instance (for redraw)
        self.canvas     = canvas      # tkinter Canvas
        self._lock      = threading.Lock()
        self._running   = False
        self._proc      = None

        if not shutil.which(self.bin):
            print(f"[GAMES] ⚠ RetroArch not found at '{self.bin}'. "
                  f"Install with: sudo apt install retroarch", flush=True)

    @property
    def available(self) -> bool:
        return bool(shutil.which(self.bin))

    def launch(self) -> str:
        """Launch RetroArch and block until it exits, then restore BMO."""
        if not self.available:
            return (f"RetroArch is not installed. "
                    f"Run: sudo apt install retroarch")

        with self._lock:
            if self._running:
                return "Game is already running."
            self._running = True

        try:
            # ── Step 1: Black out BMO screen immediately (no desktop flash) ──
            self._blackout()

            # ── Step 2: Brief yield so tkinter can paint the black frame ──────
            time.sleep(0.08)

            # ── Step 3: Launch RetroArch fullscreen ──────────────────────────
            cmd = [self.bin, "--fullscreen"] + list(self.extra_args)
            print(f"[GAMES] Launching: {' '.join(cmd)}", flush=True)

            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**os.environ, "SDL_VIDEODRIVER": "x11"},  # force x11 on Pi
            )

            # ── Step 4: Lower BMO window so RetroArch can go on top ──────────
            self._lower_window()

            # ── Step 5: Wait for RetroArch to exit ───────────────────────────
            self._proc.wait()
            print("[GAMES] RetroArch exited — restoring BMO.", flush=True)

            # ── Step 6: Restore BMO immediately (no desktop gap) ─────────────
            self._restore()
            return "Welcome back! Game session ended."

        except Exception as e:
            print(f"[GAMES] ✗ Launch error: {e}", flush=True)
            self._restore()
            return f"Could not launch games: {e}"
        finally:
            self._running = False
            self._proc    = None

    def stop(self) -> str:
        """Kill the RetroArch process if it's running."""
        with self._lock:
            if not self._running:
                return "No game is currently running."
            
            try:
                # 1. Try to terminate gracefully
                if self._proc:
                    self._proc.terminate()
                
                # 2. Hard kill if needed
                subprocess.run(["pkill", "-9", os.path.basename(self.bin)], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                return "Closing RetroArch. Returning to BMO."
            except Exception as e:
                return f"Error closing game: {e}"

    # ── Display helpers (thread-safe via tkinter .after) ────────────────────

    def _blackout(self):
        """Fill BMO window with black — runs on the tkinter thread."""
        if self.root and self.canvas:
            def _do():
                try:
                    self.canvas.configure(bg="black")
                    self.canvas.delete("all")
                    # Draw a solid black rectangle covering everything
                    w = self.root.winfo_width()  or 1920
                    h = self.root.winfo_height() or 1080
                    self.canvas.create_rectangle(0, 0, w, h,
                                                 fill="black", outline="",
                                                 tags="blackout")
                    self.root.update_idletasks()
                except Exception:
                    pass
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)
                time.sleep(0.1)   # wait for paint

    def _lower_window(self):
        """Send BMO window to the bottom of the window stack."""
        if self.root:
            def _do():
                try:
                    self.root.lower()
                    self.root.update_idletasks()
                except Exception:
                    pass
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)

    def _restore(self):
        """Raise BMO window and redraw the face — no desktop gap."""
        if self.root:
            def _do():
                try:
                    # Lift window to front
                    self.root.lift()
                    self.root.focus_force()
                    self.root.attributes("-topmost", True)
                    self.root.update_idletasks()
                    # Remove topmost after a short delay
                    self.root.after(500, lambda: self.root.attributes("-topmost", False))

                    # Restore canvas background
                    bg = getattr(self.root, "_bmo_bg", "#82D4A4")
                    self.canvas.configure(bg=bg)
                    self.canvas.delete("blackout")

                    # Trigger face redraw
                    if self.bmo_faces:
                        self.bmo_faces.draw_idle()
                except Exception as e:
                    print(f"[GAMES] Restore error: {e}", flush=True)
            if threading.current_thread() is threading.main_thread():
                _do()
            else:
                self.root.after(0, _do)
                time.sleep(0.2)
