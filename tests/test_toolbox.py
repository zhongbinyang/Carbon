#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk

from carbon_toolbox import build_app, PAGES, VERSION

assert VERSION == "26.7.7.001"
assert [page_cls.__name__ for _, page_cls in PAGES] == [
    "SerialDebugPage",
    "RegToolApp",
    "BerPage",
    "TecPage",
]
assert [title for title, _ in PAGES] == [
    "串口调试",
    "JTT1031 寄存器",
    "BER 测试",
    "TEC 温控",
]

root = tk.Tk()
pages = build_app(root)
root.update()

assert root.title() == f"Carbon ToolBox - Develop by CC Leon. Version: {VERSION}", root.title()

assert len(pages) == 4
nb = pages[0].master
assert len(nb.tabs()) == 4
assert pages[1].winfo_manager() == "notebook"

for page in pages:
    assert page.is_connected() is False
    for btn in page.op_buttons:
        assert str(btn.cget("state")) == "disabled"

for tab_id in nb.tabs():
    nb.select(tab_id)
    root.update()

for page in pages:
    page.close_page()

root.destroy()
print("test_toolbox: OK")
