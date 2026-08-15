"""A small front end for the weapon build generators.

Deliberately thin: it builds the same command line the scripts already take and shows their
output. Nothing about how a build is chosen lives here, so the scripts stay usable on their own
and there is only one place for the rules.

    python build_gui.py

Tkinter ships with Python, so there is nothing to install.
"""
import os
import queue
import subprocess
import sys
import threading
import shutil
from datetime import datetime

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from options import TOGGLES, DEFAULTS, resolve_profile

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = resolve_profile()

# Writing while either of these is running is pointless: the profile is held open and gets
# written back over the top on exit.
BLOCKERS = ("EscapeFromTarkov.exe", "SPT.Server.exe")

GENERATORS = [
    ("meta", "make_builds.py", "152 meta builds, one per weapon"),
    ("loyalty", "make_loyalty_builds.py", "608 loyalty builds, 152 weapons x 4 tiers"),
]
CHECKERS = [
    ("validate_builds.py", "conflicts and bad slots"),
    ("stock_real.py", "builds left without a stock"),
    ("sights_lights.py", "sights and lights per build"),
    ("prefs_audit.py", "did the preferences land"),
]


def running_blockers():
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=15).stdout.lower()
    except Exception:
        return []
    return [b for b in BLOCKERS if b.lower() in out]


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        root.title("SPT build generator")
        root.geometry("880x760")
        root.minsize(720, 560)

        outer = ttk.Frame(root, padding=10)
        outer.pack(fill="both", expand=True)

        # ---- preferences -------------------------------------------------
        pref = ttk.LabelFrame(outer, text="Preferences", padding=10)
        pref.pack(fill="x")
        self.vars = {}
        for name, default, label, why in TOGGLES:
            v = tk.BooleanVar(value=default)
            self.vars[name] = v
            row = ttk.Frame(pref)
            row.pack(fill="x", pady=(0, 6))
            ttk.Checkbutton(row, text=label, variable=v).pack(anchor="w")
            ttk.Label(row, text=why, wraplength=800, justify="left",
                      foreground="#666").pack(anchor="w", padx=(22, 0))

        # ---- what to build -----------------------------------------------
        which = ttk.LabelFrame(outer, text="Build", padding=10)
        which.pack(fill="x", pady=(10, 0))
        self.gen_vars = {}
        for key, script, desc in GENERATORS:
            v = tk.BooleanVar(value=True)
            self.gen_vars[key] = v
            ttk.Checkbutton(which, text=f"{key} \u2014 {desc}", variable=v).pack(anchor="w")

        self.backup = tk.BooleanVar(value=True)
        ttk.Checkbutton(which, text="Back up the profile before writing (recommended)",
                        variable=self.backup).pack(anchor="w", pady=(6, 0))

        # ---- actions ------------------------------------------------------
        act = ttk.Frame(outer)
        act.pack(fill="x", pady=10)
        self.btn_preview = ttk.Button(act, text="Preview", command=lambda: self.run(False))
        self.btn_preview.pack(side="left")
        self.btn_write = ttk.Button(act, text="Generate and write", command=lambda: self.run(True))
        self.btn_write.pack(side="left", padx=6)
        self.btn_check = ttk.Button(act, text="Run checks", command=self.run_checks)
        self.btn_check.pack(side="left")
        ttk.Button(act, text="Reset", command=self.reset).pack(side="right")

        self.status = ttk.Label(outer, text="Ready.", foreground="#555")
        self.status.pack(fill="x")

        self.out = scrolledtext.ScrolledText(outer, wrap="none", height=20,
                                             font=("Consolas", 9))
        self.out.pack(fill="both", expand=True, pady=(6, 0))
        self.out.tag_config("err", foreground="#b00")
        self.out.tag_config("ok", foreground="#070")
        self.out.tag_config("head", foreground="#03a")

        self.root.after(100, self.drain)

    # ---------------------------------------------------------------- output
    def say(self, line, tag=None):
        self.q.put((line, tag))

    def drain(self):
        while True:
            try:
                line, tag = self.q.get_nowait()
            except queue.Empty:
                break
            self.out.insert("end", line + "\n", tag or ())
            self.out.see("end")
        self.root.after(100, self.drain)

    def set_busy(self, busy, msg="Ready."):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_preview, self.btn_write, self.btn_check):
            b.config(state=state)
        self.status.config(text=msg)

    # ------------------------------------------------------------------ args
    def flags(self):
        """Only the departures from default, so the command line stays readable."""
        out = []
        for name, default, _label, _why in TOGGLES:
            if self.vars[name].get() != DEFAULTS[name]:
                out.append(f"--{name}" if self.vars[name].get() else f"--no-{name}")
        return out

    def reset(self):
        for name, default, _l, _w in TOGGLES:
            self.vars[name].set(default)
        for v in self.gen_vars.values():
            v.set(True)
        self.backup.set(True)
        self.say("Defaults restored.", "head")

    # ------------------------------------------------------------------- run
    def run(self, write):
        if self.busy:
            return
        chosen = [g for g in GENERATORS if self.gen_vars[g[0]].get()]
        if not chosen:
            messagebox.showinfo("Nothing selected", "Pick at least one of meta or loyalty.")
            return

        if write:
            blocked = running_blockers()
            if blocked:
                messagebox.showerror(
                    "Close the game first",
                    "These are running and would overwrite the profile on exit:\n\n  "
                    + "\n  ".join(blocked))
                return
            if not self.vars["conflicts"].get() and not messagebox.askyesno(
                    "Write anyway?",
                    "Part conflicts are switched off, so some builds will not assemble in game.\n\n"
                    "Write to the profile anyway?"):
                return
            if not messagebox.askyesno(
                    "Write to profile?",
                    f"This replaces the generated builds in:\n\n{PROFILE}\n\nContinue?"):
                return

        self.set_busy(True, "Working...")
        threading.Thread(target=self._work, args=(chosen, write), daemon=True).start()

    def _work(self, chosen, write):
        try:
            flags = self.flags()
            self.say("")
            self.say("=" * 78, "head")
            self.say(f"{'WRITE' if write else 'PREVIEW'}  {datetime.now():%H:%M:%S}"
                     + (f"   flags: {' '.join(flags)}" if flags else "   (all defaults)"), "head")
            self.say("=" * 78, "head")

            if write and self.backup.get():
                stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
                dst = f"{PROFILE}.bak-gui-{stamp}"
                shutil.copy2(PROFILE, dst)
                self.say(f"backup: {os.path.basename(dst)}", "ok")

            for key, script, _desc in chosen:
                self.say("")
                self.say(f"--- {script} ---", "head")
                cmd = [sys.executable, os.path.join(HERE, script), "--all"] + flags
                if write:
                    cmd.append("--write")
                if self._stream(cmd) != 0:
                    self.say(f"{script} failed - stopping.", "err")
                    self.set_busy(False, "Failed.")
                    return

            if write:
                self.say("")
                self.say("--- checks ---", "head")
                for script, _d in CHECKERS[:2]:
                    self._stream([sys.executable, os.path.join(HERE, script)], head=6)
            self.set_busy(False, "Done.")
        except Exception as e:
            self.say(f"error: {e}", "err")
            self.set_busy(False, "Failed.")

    def run_checks(self):
        if self.busy:
            return
        self.set_busy(True, "Checking...")
        threading.Thread(target=self._check_work, daemon=True).start()

    def _check_work(self):
        self.say("")
        self.say("=" * 78, "head")
        self.say(f"CHECKS  {datetime.now():%H:%M:%S}", "head")
        self.say("=" * 78, "head")
        for script, desc in CHECKERS:
            path = os.path.join(HERE, script)
            if not os.path.exists(path):
                continue
            self.say("")
            self.say(f"--- {script}  ({desc}) ---", "head")
            self._stream([sys.executable, path], head=14)
        self.set_busy(False, "Done.")

    def _stream(self, cmd, head=None):
        """Run a script, echoing its output. `head` caps how much of a chatty checker is shown."""
        try:
            p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace", bufsize=1)
        except Exception as e:
            self.say(f"could not start {cmd[1]}: {e}", "err")
            return 1
        shown = 0
        for line in p.stdout:
            line = line.rstrip()
            if head is not None and shown >= head:
                shown += 1
                continue
            shown += 1
            tag = "err" if ("Traceback" in line or "Error" in line or "error" in line) else None
            self.say("  " + line, tag)
        p.wait()
        if head is not None and shown > head:
            self.say(f"  ... {shown - head} more lines")
        return p.returncode


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
