#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Generic serial debug page."""

import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

import serial_debug
from toolbox.base_page import BasePage


class SerialDebugPage(BasePage):
    default_baud = "115200"
    show_address = False
    bridge_logger = serial_debug.logger

    def build_body(self, parent):
        frame = ttk.LabelFrame(parent, text=" Serial Debug ")
        frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)
        parent.rowconfigure(0, weight=1)

        ttk.Label(frame, text="Mode:").grid(row=0, column=0, padx=5, pady=6, sticky="e")
        self.mode_combo = ttk.Combobox(frame, values=["HEX", "Text"], state="readonly", width=10)
        self.mode_combo.set("HEX")
        self.mode_combo.grid(row=0, column=1, padx=5, pady=6, sticky="w")

        ttk.Label(frame, text="Line ending:").grid(row=0, column=2, padx=5, pady=6, sticky="e")
        self.line_combo = ttk.Combobox(frame, values=["None", "CR", "LF", "CRLF"], state="readonly", width=8)
        self.line_combo.set("None")
        self.line_combo.grid(row=0, column=3, padx=5, pady=6, sticky="w")

        ttk.Label(frame, text="Send:").grid(row=1, column=0, padx=5, pady=6, sticky="ne")
        self.input_text = tk.Text(frame, height=4, font=("Consolas", 10), wrap="word")
        self.input_text.insert("1.0", "A5 00")
        self.input_text.grid(row=1, column=1, columnspan=3, sticky="ew", padx=5, pady=6)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=4, sticky="n", padx=5, pady=6)
        self.btn_send = ttk.Button(btn_frame, text="Send", style="Primary.TButton", width=12, command=self.op_send)
        self.btn_send.grid(row=0, column=0, pady=3)
        self.op_buttons.append(self.btn_send)
        self.btn_read = ttk.Button(btn_frame, text="Read", width=12, command=self.op_read)
        self.btn_read.grid(row=1, column=0, pady=3)
        self.op_buttons.append(self.btn_read)
        self.btn_clear_output = ttk.Button(btn_frame, text="Clear", width=12, command=self.clear_output)
        self.btn_clear_output.grid(row=2, column=0, pady=3)

        ttk.Label(frame, text="Traffic:").grid(row=2, column=0, padx=5, pady=6, sticky="ne")
        self.output_text = scrolledtext.ScrolledText(
            frame, height=12, font=("Consolas", 10), background="#101418", foreground="#D4D4D4")
        self.output_text.grid(row=2, column=1, columnspan=4, sticky="nsew", padx=5, pady=6)

    def create_controller(self, port, baud, address):
        return serial_debug.SerialDebugController(port_name=port, baudrate=baud)

    def op_send(self):
        text = self.input_text.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("Parameter error", "send data cannot be empty")
            return

        def do(controller):
            if self.mode_combo.get() == "HEX":
                sent = controller.send_hex(text)
                return ("tx", "HEX", sent)
            sent = controller.send_text(text, encoding="utf-8", line_ending=self.line_combo.get())
            return ("tx", "TEXT", sent)

        self.start_op("serial send", do)

    def op_read(self):
        self.start_op("serial read", lambda controller: ("rx", "HEX", controller.read_available()))

    def render_result(self, result):
        direction, mode, data = result
        if direction == "rx" and not data:
            self._append_output("RX", "No data")
            return
        label = "TX" if direction == "tx" else "RX"
        hex_text = data.hex(" ").upper()
        ascii_text = data.decode("utf-8", errors="replace").replace("\r", "\\r").replace("\n", "\\n")
        self._append_output(f"{label} {mode}", f"HEX: {hex_text}\nASCII: {ascii_text}")

    def _append_output(self, title, body):
        timestamp = time.strftime("%H:%M:%S")
        self.output_text.insert(tk.END, f"[{timestamp}] {title}\n{body}\n\n")
        self.output_text.see(tk.END)

    def clear_output(self):
        self.output_text.delete("1.0", tk.END)
