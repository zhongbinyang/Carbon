#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk
from tkinter import ttk

from toolbox.base_page import setup_style
from toolbox.pages.jtt1031_iic_page import Jtt1031IicPage

import toolbox.base_page as _bp


class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


_bp.threading.Thread = _SyncThread


class FakeJttController:
    def __init__(self):
        self.serial = self
        self.is_open = True
        self.address = 0
        self.calls = []

    def open(self):
        pass

    def close(self):
        self.is_open = False

    def read_register_iic(self, **kwargs):
        self.calls.append(("read-reg", kwargs))
        return b"ABCD"

    def write_register_iic(self, **kwargs):
        self.calls.append(("write-reg", kwargs))
        return True

    def read_module_page(self, **kwargs):
        self.calls.append(("read-page", kwargs))
        return bytes(range(128))

    def write_module_page(self, **kwargs):
        self.calls.append(("write-page", kwargs))
        return True


def pump(root, cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        root.update()
        time.sleep(0.01)


root = tk.Tk()
setup_style(root)
nb = ttk.Notebook(root)
nb.pack()
page = Jtt1031IicPage(nb)
nb.add(page, text="jtt")
root.update()

assert page.baud_combo.get() == "115200"
assert page.entry_address.get() == "0"
assert page.mode_combo.get() == "Register"
assert str(page.btn_read.cget("state")) == "disabled"

page.controller = FakeJttController()
page.update_btn_states(True)

page.entry_port.delete(0, tk.END)
page.entry_port.insert(0, "3")
page.entry_dev.delete(0, tk.END)
page.entry_dev.insert(0, "A0")
page.entry_start.delete(0, tk.END)
page.entry_start.insert(0, "10")
page.entry_size.delete(0, tk.END)
page.entry_size.insert(0, "4")
page.op_read()
root.update()
assert page.lbl_read_hex.cget("text") == "41 42 43 44"
assert page.controller.calls[0] == ("read-reg", {
    "port": 3, "dev_address": 0xA0, "start_reg": 0x10, "size": 4
})

page.entry_write_data.delete(0, tk.END)
page.entry_write_data.insert(0, "AA BB")
page.op_write()
pump(root, lambda: len(page.controller.calls) >= 2 and not page.busy)
assert page.controller.calls[1] == ("write-reg", {
    "port": 3, "dev_address": 0xA0, "start_reg": 0x10, "data": [0xAA, 0xBB]
})

page.mode_combo.set("Page")
page._on_mode_change()
page.entry_part.delete(0, tk.END)
page.entry_part.insert(0, "2")
page.entry_page.delete(0, tk.END)
page.entry_page.insert(0, "7")
page.entry_start.delete(0, tk.END)
page.entry_start.insert(0, "1")
page.entry_size.delete(0, tk.END)
page.entry_size.insert(0, "3")
page.op_read()
pump(root, lambda: len(page.controller.calls) >= 3 and page.lbl_read_hex.cget("text") != "Reading...")
assert page.lbl_read_hex.cget("text") == "01 02 03"
assert page.controller.calls[2] == ("read-page", {"port": 3, "part": 2, "page": 7})

root.destroy()
print("test_jtt1031_iic_page: OK")
