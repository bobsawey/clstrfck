"""Proof-of-concept for macOS system-wide automation with permissions checks.

WARNING: Use at your own risk. This script can request accessibility access
which allows controlling mouse and keyboard events across the system.
"""

import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

WARNING_TEXT = (
    "USE AT YOUR OWN RISK!\n"
    "Granting accessibility permissions allows full control over your Mac."
)
PROMPT_SENTENCE = "I understand the risks"


def is_accessibility_enabled() -> bool:
    """Return True if the process has accessibility permissions on macOS."""
    if sys.platform != "darwin":
        return True
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to return UI elements enabled'],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip().lower() == "true"
    except Exception:
        return False


def permission_instructions() -> str:
    return (
        "Accessibility permission not granted.\n"
        "Open System Settings → Privacy & Security → Accessibility and add this\n"
        "application, or run the following command with sudo to force-enable:\n"
        "  sudo tccutil reset Accessibility\n"
        "Then rerun this tool."
    )


def on_start() -> None:
    if not is_accessibility_enabled():
        messagebox.showwarning("Permission required", permission_instructions())
        return
    messagebox.showinfo("Ready", "Accessibility granted; automation would start here.")


def main() -> None:
    root = tk.Tk()
    root.title("Atzmo macOS automation POC")

    tk.Label(root, text=WARNING_TEXT, fg="red", wraplength=400, justify="left").pack(pady=10)

    tk.Label(root, text=f'Type "{PROMPT_SENTENCE}" to enable automation:').pack()
    entry_var = tk.StringVar()
    entry = tk.Entry(root, textvariable=entry_var, width=40)
    entry.pack(pady=5)
    button = tk.Button(root, text="Enable Automation", state="disabled", command=on_start)
    button.pack(pady=5)

    def on_change(*_args) -> None:
        if entry_var.get().strip() == PROMPT_SENTENCE:
            button.config(state="normal")
        else:
            button.config(state="disabled")

    entry_var.trace_add("write", on_change)
    root.mainloop()


if __name__ == "__main__":
    main()
