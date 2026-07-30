#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Carbon ToolBox multi-tab serial test utility."""

import tkinter as tk
from tkinter import ttk

from jtt1031_reg_tool import RegToolApp
from toolbox.base_page import setup_style
from toolbox.pages.serial_debug_page import SerialDebugPage
from toolbox.pages.ber_page import BerPage
from toolbox.pages.tec_page import TecPage

VERSION = "26.7.7.001"

PAGES = [
    ("串口调试", SerialDebugPage),
    ("JTT1031 寄存器", RegToolApp),
    ("BER 测试", BerPage),
    ("TEC 温控", TecPage),
]


def build_app(root):
    """Build the main window and return page instances for tests/cleanup."""
    root.title(f"Carbon ToolBox - Develop by CC Leon. Version: {VERSION}")
    setup_style(root)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    pages = []
    for title, page_cls in PAGES:
        page = page_cls(notebook)
        notebook.add(page, text=f"  {title}  ")
        pages.append(page)
    return pages


def main():
    root = tk.Tk()
    root.geometry("900x760")
    root.minsize(840, 700)
    pages = build_app(root)

    def on_close():
        for page in pages:
            page.close_page()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
