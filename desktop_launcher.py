"""Small Tkinter desktop launcher for the GoScore local server."""
from __future__ import annotations
import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox

BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
if getattr(sys, "frozen", False):
    # PyInstaller unpacks bundled web assets into _MEIPASS. server.py derives its
    # WEB path from its own location, so keep the bundled web directory there.
    pass

from goscore.server import make_server

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://localhost:{PORT}/"

class GoScoreLauncher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.server = None
        self.app = None
        self.server_thread = None
        self.closing = False
        root.title("GoScore")
        root.geometry("440x250")
        root.minsize(420, 230)
        root.protocol("WM_DELETE_WINDOW", self.close)
        tk.Label(root, text="GoScore", font=("Segoe UI", 20, "bold")).pack(pady=(18, 2))
        tk.Label(root, text="Cricket · Football · OBS Graphics", font=("Segoe UI", 10)).pack()
        self.status = tk.StringVar(value="Server is stopped")
        tk.Label(root, textvariable=self.status, font=("Segoe UI", 10), wraplength=380).pack(pady=14)
        row = tk.Frame(root)
        row.pack(pady=4)
        self.start_btn = tk.Button(row, text="Start GoScore", width=14, command=self.start)
        self.start_btn.pack(side="left", padx=5)
        self.open_btn = tk.Button(row, text="Open GoScore", width=14, command=self.open_app, state="disabled")
        self.open_btn.pack(side="left", padx=5)
        self.stop_btn = tk.Button(row, text="Stop", width=10, command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        tk.Label(root, text="Keep this window open while using GoScore.", fg="#666", font=("Segoe UI", 9)).pack(pady=(12, 0))

    def start(self):
        if self.server is not None:
            self.open_app()
            return
        try:
            data_dir = os.path.join(BASE_DIR, "data")
            output_dir = os.path.join(BASE_DIR, "output")
            os.makedirs(data_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
            self.server, self.app = make_server(HOST, PORT, data_dir, output_dir, None)
            self.server_thread = threading.Thread(target=self.server.serve_forever, name="GoScoreServer", daemon=True)
            self.server_thread.start()
            self.status.set(f"GoScore is running at {URL}")
            self.start_btn.config(state="disabled")
            self.open_btn.config(state="normal")
            self.stop_btn.config(state="normal")
            self.root.after(350, self.open_app)
        except OSError as exc:
            self.server = None
            self.app = None
            messagebox.showerror("Could not start GoScore", f"GoScore could not start. Port {PORT} may already be in use.\n\nDetails: {exc}")
        except Exception as exc:
            self.server = None
            self.app = None
            messagebox.showerror("Could not start GoScore", f"GoScore encountered a startup error.\n\nDetails: {exc}")

    def open_app(self):
        webbrowser.open(URL)

    def stop(self):
        if self.server is not None:
            try:
                self.server.shutdown()
                self.server.server_close()
                if self.app is not None:
                    self.app.stop.set()
            finally:
                self.server = None
                self.app = None
        self.status.set("Server is stopped")
        self.start_btn.config(state="normal")
        self.open_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")

    def close(self):
        if self.server is not None:
            if not messagebox.askyesno("Close GoScore", "Stop the GoScore server and close the launcher?"):
                return
            self.stop()
        self.closing = True
        self.root.destroy()

if __name__ == "__main__":
    window = tk.Tk()
    GoScoreLauncher(window)
    window.mainloop()
