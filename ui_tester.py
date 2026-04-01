from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import pyautogui

from text_finder import locate_text_match


def _parse_region(region_text: str):
    region_text = region_text.strip()
    if not region_text:
        return None
    parts = [p.strip() for p in region_text.split(",")]
    if len(parts) != 4:
        raise ValueError("Region must be: left,top,width,height")
    left, top, width, height = (int(p) for p in parts)
    return (left, top, width, height)


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.master = master
        self.grid(sticky="nsew")

        master.title("OCR Coordinate Finder - UI Tester")
        master.minsize(720, 520)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.word_var = tk.StringVar(value="Multiplayer")
        self.letter_var = tk.StringVar(value="")
        self.letter_index_var = tk.IntVar(value=0)
        self.window_title_var = tk.StringVar(value="")
        self.region_var = tk.StringVar(value="")
        self.min_conf_var = tk.DoubleVar(value=60.0)
        self.match_strategy_var = tk.StringVar(value="best")
        self.match_index_var = tk.IntVar(value=0)
        self.case_insensitive_var = tk.BooleanVar(value=False)
        self.contains_var = tk.BooleanVar(value=False)
        self.lang_var = tk.StringVar(value="eng")
        self.psm_var = tk.StringVar(value="")
        self.precise_letter_var = tk.BooleanVar(value=False)
        self.move_var = tk.BooleanVar(value=False)
        self.click_var = tk.BooleanVar(value=False)

        self._build()

    def _build(self) -> None:
        inputs = ttk.LabelFrame(self, text="Inputs", padding=10)
        inputs.grid(row=0, column=0, sticky="nsew")
        inputs.columnconfigure(1, weight=1)

        def row(parent, label: str, widget, r: int):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
            widget.grid(row=r, column=1, sticky="ew", pady=4)

        row(inputs, "Word", ttk.Entry(inputs, textvariable=self.word_var), 0)
        row(inputs, "Letter (optional)", ttk.Entry(inputs, textvariable=self.letter_var), 1)

        li = ttk.Frame(inputs)
        ttk.Label(li, text="Letter index").pack(side="left")
        ttk.Spinbox(li, from_=0, to=999, textvariable=self.letter_index_var, width=6).pack(
            side="left", padx=(8, 0)
        )
        ttk.Checkbutton(li, text="Precise letter boxing", variable=self.precise_letter_var).pack(
            side="left", padx=(12, 0)
        )
        li.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(inputs, text="").grid(row=2, column=0)  # spacer label

        row(inputs, "Window title (optional)", ttk.Entry(inputs, textvariable=self.window_title_var), 3)
        row(inputs, "Region (optional: left,top,width,height)", ttk.Entry(inputs, textvariable=self.region_var), 4)

        opts = ttk.LabelFrame(self, text="Options", padding=10)
        opts.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        opts.columnconfigure(1, weight=1)

        row2 = 0
        row(
            opts,
            "Min confidence (0-100)",
            ttk.Spinbox(opts, from_=0, to=100, increment=1, textvariable=self.min_conf_var),
            row2,
        )
        row2 += 1

        ms = ttk.Frame(opts)
        ttk.Label(ms, text="Match strategy").pack(side="left")
        ttk.Combobox(ms, values=["best", "first"], textvariable=self.match_strategy_var, width=8, state="readonly").pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(ms, text="Match index").pack(side="left", padx=(12, 0))
        ttk.Spinbox(ms, from_=0, to=999, textvariable=self.match_index_var, width=6).pack(side="left", padx=(8, 0))
        ms.grid(row=row2, column=1, sticky="w", pady=4)
        ttk.Label(opts, text="").grid(row=row2, column=0)
        row2 += 1

        flags = ttk.Frame(opts)
        ttk.Checkbutton(flags, text="Case-insensitive", variable=self.case_insensitive_var).pack(side="left")
        ttk.Checkbutton(flags, text="Allow contains", variable=self.contains_var).pack(side="left", padx=(12, 0))
        flags.grid(row=row2, column=1, sticky="w", pady=4)
        ttk.Label(opts, text="").grid(row=row2, column=0)
        row2 += 1

        tl = ttk.Frame(opts)
        ttk.Label(tl, text="Lang").pack(side="left")
        ttk.Entry(tl, textvariable=self.lang_var, width=10).pack(side="left", padx=(8, 0))
        ttk.Label(tl, text="PSM (optional)").pack(side="left", padx=(12, 0))
        ttk.Entry(tl, textvariable=self.psm_var, width=6).pack(side="left", padx=(8, 0))
        tl.grid(row=row2, column=1, sticky="w", pady=4)
        ttk.Label(opts, text="").grid(row=row2, column=0)
        row2 += 1

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)

        ttk.Checkbutton(actions, text="Move mouse to coords", variable=self.move_var).pack(side="left")
        ttk.Checkbutton(actions, text="Click after move", variable=self.click_var).pack(side="left", padx=(12, 0))

        self.run_btn = ttk.Button(actions, text="Run OCR", command=self._on_run)
        self.run_btn.pack(side="right")

        out = ttk.LabelFrame(self, text="Output", padding=10)
        out.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)

        self.output = tk.Text(out, height=10, wrap="word")
        self.output.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(out, orient="vertical", command=self.output.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=sb.set)

    def _log(self, s: str) -> None:
        self.output.insert("end", s + "\n")
        self.output.see("end")

    def _set_running(self, running: bool) -> None:
        self.run_btn.configure(state=("disabled" if running else "normal"))

    def _on_run(self) -> None:
        self._set_running(True)
        self._log("Running OCR...")

        def work():
            try:
                word = self.word_var.get().strip()
                letter = self.letter_var.get().strip() or None
                if letter is not None and len(letter) != 1:
                    raise ValueError("Letter must be exactly 1 character.")

                window_title = self.window_title_var.get().strip() or None
                region = _parse_region(self.region_var.get())
                psm_txt = self.psm_var.get().strip()
                psm = int(psm_txt) if psm_txt else None

                match = locate_text_match(
                    word,
                    letter=letter,
                    letter_index=int(self.letter_index_var.get()),
                    window_title=window_title,
                    region=region,
                    min_conf=float(self.min_conf_var.get()),
                    match_strategy=self.match_strategy_var.get(),
                    match_index=int(self.match_index_var.get()),
                    case_sensitive=not bool(self.case_insensitive_var.get()),
                    allow_contains=bool(self.contains_var.get()),
                    lang=self.lang_var.get().strip() or "eng",
                    psm=psm,
                    precise_letter=bool(self.precise_letter_var.get()),
                )

                if match is None:
                    self.master.after(0, lambda: self._log("No match found."))
                    return

                def done():
                    self._log(f"coords: {match.coords}")
                    self._log(f"bbox:   {match.bbox}  (left, top, width, height)")
                    self._log(f"conf:   {match.confidence}")
                    self._log(f"text:   {match.matched_text!r}")
                    self._log(f"region: {match.source_region}  (capture region)")
                    if self.move_var.get() or self.click_var.get():
                        pyautogui.moveTo(match.coords[0], match.coords[1], duration=0.25)
                    if self.click_var.get():
                        pyautogui.click()

                self.master.after(0, done)
            except Exception as e:
                self.master.after(0, lambda: self._log(f"Error: {e}"))
            finally:
                self.master.after(0, lambda: self._set_running(False))

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    root = tk.Tk()
    # Better default styling on Windows
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

