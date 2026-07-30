#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""JTT1031 direct IIC page."""

import tkinter as tk
from tkinter import ttk, messagebox

import jtt1031_iic
from toolbox.base_page import BasePage


def parse_num(value):
    value = value.strip()
    if value.lower().startswith("0x"):
        return int(value, 16)
    try:
        return int(value, 16)
    except ValueError:
        return int(value)


def parse_hex_list(value):
    raw = value.replace(",", " ").replace("0x", "").replace("0X", "")
    items = raw.split()
    if not items:
        raise ValueError("write data cannot be empty")
    return [int(item, 16) for item in items]


class Jtt1031IicPage(BasePage):
    default_baud = "115200"
    show_address = True
    address_label = "Board addr:"
    default_address = "0"
    bridge_logger = jtt1031_iic.logger

    def build_body(self, parent):
        param_frame = ttk.LabelFrame(parent, text=" JTT1031 IIC Direct ")
        param_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for col in range(6):
            param_frame.columnconfigure(col, weight=1)

        ttk.Label(param_frame, text="Mode:").grid(row=0, column=0, padx=5, pady=6, sticky="e")
        self.mode_combo = ttk.Combobox(param_frame, values=["Register", "Page"], state="readonly", width=12)
        self.mode_combo.set("Register")
        self.mode_combo.grid(row=0, column=1, padx=5, pady=6, sticky="w")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _evt: self._on_mode_change())

        ttk.Label(param_frame, text="Module port:").grid(row=0, column=2, padx=5, pady=6, sticky="e")
        self.entry_port = ttk.Entry(param_frame, width=12)
        self.entry_port.insert(0, "0")
        self.entry_port.grid(row=0, column=3, padx=5, pady=6, sticky="w")

        self.dev_label = ttk.Label(param_frame, text="Dev addr:")
        self.dev_label.grid(row=0, column=4, padx=5, pady=6, sticky="e")
        self.entry_dev = ttk.Entry(param_frame, width=12)
        self.entry_dev.insert(0, "A0")
        self.entry_dev.grid(row=0, column=5, padx=5, pady=6, sticky="w")

        self.part_label = ttk.Label(param_frame, text="Part:")
        self.part_label.grid(row=1, column=0, padx=5, pady=6, sticky="e")
        self.entry_part = ttk.Entry(param_frame, width=12)
        self.entry_part.insert(0, "1")
        self.entry_part.grid(row=1, column=1, padx=5, pady=6, sticky="w")

        self.page_label = ttk.Label(param_frame, text="Page:")
        self.page_label.grid(row=1, column=2, padx=5, pady=6, sticky="e")
        self.entry_page = ttk.Entry(param_frame, width=12)
        self.entry_page.insert(0, "0")
        self.entry_page.grid(row=1, column=3, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="Start:").grid(row=1, column=4, padx=5, pady=6, sticky="e")
        self.entry_start = ttk.Entry(param_frame, width=12)
        self.entry_start.insert(0, "00")
        self.entry_start.grid(row=1, column=5, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="Length:").grid(row=2, column=0, padx=5, pady=6, sticky="e")
        self.entry_size = ttk.Entry(param_frame, width=12)
        self.entry_size.insert(0, "16")
        self.entry_size.grid(row=2, column=1, padx=5, pady=6, sticky="w")

        op_frame = ttk.LabelFrame(parent, text=" Operation ")
        op_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        op_frame.columnconfigure(1, weight=1)

        ttk.Label(op_frame, text="Write data:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.entry_write_data = ttk.Entry(op_frame)
        self.entry_write_data.insert(0, "11 22 33 44")
        self.entry_write_data.grid(row=0, column=1, columnspan=2, padx=5, pady=8, sticky="ew")

        btn_frame = ttk.Frame(op_frame)
        btn_frame.grid(row=1, column=0, columnspan=3, pady=8)
        self.btn_read = ttk.Button(btn_frame, text="Read", style="Primary.TButton", width=18, command=self.op_read)
        self.btn_read.grid(row=0, column=0, padx=15)
        self.op_buttons.append(self.btn_read)
        self.btn_write = ttk.Button(btn_frame, text="Write", style="Success.TButton", width=18, command=self.op_write)
        self.btn_write.grid(row=0, column=1, padx=15)
        self.op_buttons.append(self.btn_write)

        result_frame = ttk.Frame(op_frame)
        result_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=2)
        ttk.Label(result_frame, text="HEX:", font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=5)
        self.lbl_read_hex = ttk.Label(result_frame, text="-", font=("Consolas", 10, "bold"), foreground="#0078D4")
        self.lbl_read_hex.pack(side="left", padx=5)
        ttk.Label(result_frame, text="ASCII:", font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=5)
        self.lbl_read_ascii = ttk.Label(result_frame, text="-", font=("Consolas", 10, "bold"), foreground="#107C41")
        self.lbl_read_ascii.pack(side="left", padx=5)
        self.lbl_write_status = ttk.Label(op_frame, text="-", foreground="#107C41")
        self.lbl_write_status.grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=5)

        self._on_mode_change()

    def create_controller(self, port, baud, address):
        return jtt1031_iic.JTT1031IICController(port_name=port, baudrate=baud, address=address)

    def _on_mode_change(self):
        is_page = self.mode_combo.get() == "Page"
        part_state = "normal" if is_page else "disabled"
        dev_state = "disabled" if is_page else "normal"
        for widget in (self.entry_part, self.entry_page):
            widget.configure(state=part_state)
        self.entry_dev.configure(state=dev_state)

    def _read_common(self):
        return {
            "mode": self.mode_combo.get(),
            "port": parse_num(self.entry_port.get()),
            "dev_address": parse_num(self.entry_dev.get()) if self.mode_combo.get() == "Register" else None,
            "part": parse_num(self.entry_part.get()) if self.mode_combo.get() == "Page" else None,
            "page": parse_num(self.entry_page.get()) if self.mode_combo.get() == "Page" else None,
            "start": parse_num(self.entry_start.get()),
            "size": int(self.entry_size.get()),
        }

    def op_read(self):
        try:
            params = self._read_common()
            if params["mode"] == "Register" and not 1 <= params["size"] <= 128:
                raise ValueError("register read length must be 1..128")
            if params["mode"] == "Page" and not (0 <= params["start"] <= 127 and 1 <= params["size"] <= 128
                                                  and params["start"] + params["size"] <= 128):
                raise ValueError("page read range must stay within 0..127")
        except ValueError as exc:
            messagebox.showerror("Parameter error", str(exc))
            return

        self.lbl_read_hex.config(text="Reading...")
        self.lbl_read_ascii.config(text="")

        def do(controller):
            if params["mode"] == "Register":
                data = controller.read_register_iic(
                    port=params["port"],
                    dev_address=params["dev_address"],
                    start_reg=params["start"],
                    size=params["size"],
                )
            else:
                page_data = controller.read_module_page(
                    port=params["port"],
                    part=params["part"],
                    page=params["page"],
                )
                data = page_data[params["start"]:params["start"] + params["size"]]
            return ("read", data)

        self.start_op("JTT1031 IIC read", do)

    def op_write(self):
        try:
            params = self._read_common()
            data = parse_hex_list(self.entry_write_data.get())
            if params["mode"] == "Register" and not 1 <= len(data) <= 128:
                raise ValueError("register write length must be 1..128")
            if params["mode"] == "Page" and not (0 <= params["start"] <= 127 and
                                                 params["start"] + len(data) <= 128):
                raise ValueError("page write range must stay within 0..127")
        except ValueError as exc:
            messagebox.showerror("Parameter error", str(exc))
            return

        def do(controller):
            if params["mode"] == "Register":
                controller.write_register_iic(
                    port=params["port"],
                    dev_address=params["dev_address"],
                    start_reg=params["start"],
                    data=data,
                )
            else:
                controller.write_module_page(
                    port=params["port"],
                    part=params["part"],
                    page=params["page"],
                    start_addr=params["start"],
                    data=data,
                )
            return ("write", len(data))

        self.start_op("JTT1031 IIC write", do)

    def render_result(self, result):
        kind, payload = result
        if kind == "read":
            self.lbl_read_hex.config(text=payload.hex(" ").upper() or "(empty)")
            self.lbl_read_ascii.config(text=payload.decode("ascii", errors="replace").replace("\r", " ").replace("\n", " "))
        elif kind == "write":
            self.lbl_write_status.config(text=f"Write OK: {payload} byte(s)")
