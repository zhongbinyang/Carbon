#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk
from tkinter import ttk

import toolbox.base_page as _bp
from toolbox.base_page import setup_style
from toolbox.pages.serial_debug_page import SerialDebugPage


class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


_bp.threading.Thread = _SyncThread


class FakeDebugController:
    def __init__(self):
        self.serial = self
        self.is_open = True
        self.calls = []

    def open(self):
        pass

    def close(self):
        self.is_open = False

    def send_hex(self, text):
        self.calls.append(("hex", text))
        return bytes([0xA5, 0x01])

    def send_text(self, text, encoding="utf-8", line_ending=""):
        self.calls.append(("text", text, encoding, line_ending))
        return (text + "\r\n").encode("ascii")

    def read_available(self, max_bytes=4096):
        self.calls.append(("read", max_bytes))
        return b"OK\r\n"


def pump(root, cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        root.update()
        time.sleep(0.01)


root = tk.Tk()
setup_style(root)
nb = ttk.Notebook(root)
nb.pack()
page = SerialDebugPage(nb)
nb.add(page, text="debug")
root.update()

assert page.baud_combo.get() == "115200"
assert page.mode_combo.get() == "HEX"
assert str(page.btn_send.cget("state")) == "disabled"

page.controller = FakeDebugController()
page.update_btn_states(True)

page.input_text.delete("1.0", tk.END)
page.input_text.insert("1.0", "A5 01")
page.op_send()
pump(root, lambda: "TX HEX" in page.output_text.get("1.0", "end"))
assert page.controller.calls[0] == ("hex", "A5 01")

page.mode_combo.set("Text")
page.line_combo.set("CRLF")
page.input_text.delete("1.0", tk.END)
page.input_text.insert("1.0", "T0")
page.op_send()
pump(root, lambda: len(page.controller.calls) >= 2 and not page.busy)
assert page.controller.calls[1] == ("text", "T0", "utf-8", "CRLF")

page.op_read()
pump(root, lambda: "RX HEX" in page.output_text.get("1.0", "end"))
assert page.controller.calls[2] == ("read", 4096)

root.destroy()
print("test_serial_debug_page: OK")
