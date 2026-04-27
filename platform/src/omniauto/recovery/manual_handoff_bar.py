"""Topmost bottom bar for manual handoff reminders."""

from __future__ import annotations

import argparse
import tkinter as tk


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show a non-blocking manual handoff reminder bar.")
    parser.add_argument("--title", default="Manual Handoff")
    parser.add_argument("--message", default="Manual verification required.")
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    root = tk.Tk()
    root.title(args.title)
    root.overrideredirect(True)
    root.configure(bg="#000000")
    root.attributes("-topmost", True)

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    width = min(1040, max(640, screen_width - 120))
    height = 94
    x_pos = max(16, (screen_width - width) // 2)
    y_pos = max(16, screen_height - height - 42)
    root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    container = tk.Frame(root, bg="#000000", bd=0, highlightthickness=1, highlightbackground="#333333")
    container.pack(fill="both", expand=True)

    message_label = tk.Label(
        container,
        text=args.message,
        bg="#000000",
        fg="#FFFFFF",
        font=("Microsoft YaHei UI", 15, "bold"),
        anchor="w",
        justify="left",
        padx=24,
        pady=14,
    )
    message_label.pack(fill="x")

    subtitle_text = args.subtitle or "Press Esc to dismiss this reminder."
    subtitle_label = tk.Label(
        container,
        text=subtitle_text,
        bg="#000000",
        fg="#C7C7C7",
        font=("Microsoft YaHei UI", 10),
        anchor="w",
        justify="left",
        padx=24,
        pady=0,
    )
    subtitle_label.pack(fill="x")

    def _close(_: object | None = None) -> None:
        try:
            root.destroy()
        except tk.TclError:
            pass

    root.bind("<Escape>", _close)
    root.bind("<Button-1>", _close)
    root.after(max(5, args.timeout_seconds) * 1000, _close)
    root.mainloop()


if __name__ == "__main__":
    main()
