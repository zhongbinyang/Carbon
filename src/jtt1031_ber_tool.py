#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Standalone JTT1031/1030 TEC-100G BERT test tool.

Usage:
    python src/jtt1031_ber_tool.py

Commands are defined by section 4.1 of
``阶梯科技测试系统--底层通信协议JTT1031``: 0x3101 through 0x3106.

The document describes an 81-byte status payload. Captured firmware frames use
an 80-byte payload with mode/rate/check directly after the first control or
status byte. Both layouts are decoded explicitly and displayed by the GUI.
"""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

import serial
import serial.tools.list_ports


logger = logging.getLogger("JTT1031_BER_TOOL")

CMD_STATUS = 0x3101
CMD_CONTROL = 0x3102
CMD_CHECK_MODE = 0x3103
CMD_CLEAR = 0x3104
CMD_RATE = 0x3105
CMD_MODE = 0x3106

PRBS_MODES = {
    "PRBS7": 0,
    "PRBS9": 1,
    "PRBS15": 2,
    "PRBS23": 3,
    "PRBS31": 4,
}
PRBS_MODE_NAMES = {value: name for name, value in PRBS_MODES.items()}

RATES = {"25.78G": 1, "26.5625G": 2}
RATE_NAMES = {value: name for name, value in RATES.items()}

CHECK_MODES = {"RATIO": 1, "COUNT": 2}
CHECK_MODE_NAMES = {value: name for name, value in CHECK_MODES.items()}

BAUD_CHOICES = ["9600", "19200", "38400", "57600", "115200"]


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _u8(value: int, name: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be 0..255")
    return value


def build_frame(address: int, command: int, data: bytes = b"") -> bytes:
    address = _u8(address, "address")
    if not isinstance(command, int) or not 0 <= command <= 0xFFFF:
        raise ValueError("command must be 0..65535")
    data = bytes(data)
    length = 7 + len(data)
    if length > 0xFFFF:
        raise ValueError("frame is too long")
    frame = bytearray([
        0xA5,
        address,
        (length >> 8) & 0xFF,
        length & 0xFF,
        (command >> 8) & 0xFF,
        command & 0xFF,
    ])
    frame.extend(data)
    frame.append(checksum(frame))
    return bytes(frame)


def parse_response(
    frame: bytes,
    expect_address: int,
    expect_command: int,
) -> bytes:
    frame = bytes(frame)
    if len(frame) < 7:
        raise ValueError("response too short")
    if frame[0] != 0x5A:
        raise ValueError(f"bad response head: 0x{frame[0]:02X}")
    if frame[1] != _u8(expect_address, "address"):
        raise ValueError("response address mismatch")
    declared_length = int.from_bytes(frame[2:4], "big")
    if declared_length != len(frame):
        raise ValueError(
            f"response length mismatch: declared {declared_length}, got {len(frame)}"
        )
    if checksum(frame[:-1]) != frame[-1]:
        raise ValueError("response checksum error")
    command = int.from_bytes(frame[4:6], "big")
    if command != expect_command:
        raise ValueError(
            f"response command mismatch: expected 0x{expect_command:04X}, got 0x{command:04X}"
        )
    return frame[6:-1]


def _read_u32_list(data: bytes, offset: int) -> tuple[list[int], int]:
    values = [
        int.from_bytes(data[offset + index * 4:offset + (index + 1) * 4], "big")
        for index in range(4)
    ]
    return values, offset + 16


def _read_s32_list(data: bytes, offset: int) -> tuple[list[int], int]:
    values = [
        int.from_bytes(
            data[offset + index * 4:offset + (index + 1) * 4],
            "big",
            signed=True,
        )
        for index in range(4)
    ]
    return values, offset + 16


@dataclass
class BerStatus:
    layout: str
    control: int
    fec_on: Optional[bool]
    tx_mode: int
    tx_rate: int
    check_mode: int
    ppg_lock: list[int]
    ed_lock: list[int]
    runtime_s: int
    error_time: list[int]
    error_count: list[int]
    ber_mantissa: list[int]
    ber_exponent: list[int]
    raw: bytes = field(repr=False)

    def ber_strings(self) -> list[str]:
        return [
            f"{mantissa}e{exponent}"
            for mantissa, exponent in zip(self.ber_mantissa, self.ber_exponent)
        ]


def parse_status(payload: bytes) -> BerStatus:
    """Decode either the captured 80-byte or documented 81-byte status data."""
    data = bytes(payload)
    if len(data) == 80:
        layout = "observed80"
        control = data[0]
        fec_on = None
        tx_mode = data[1]
        tx_rate = data[2]
        check_mode = data[3]
        ppg_lock = list(data[4:8])
        ed_lock = list(data[8:12])
        offset = 12
    elif len(data) == 81:
        layout = "documented81"
        control = data[0]
        fec_on = bool(data[1])
        tx_mode = data[2]
        tx_rate = data[3]
        ppg_lock = list(data[4:8])
        ed_lock = list(data[8:12])
        check_mode = data[12]
        offset = 13
    else:
        raise ValueError(
            f"unsupported BER status length: {len(data)}; expected 80 or 81 bytes"
        )

    runtime_s = int.from_bytes(data[offset:offset + 4], "big")
    offset += 4
    error_time, offset = _read_u32_list(data, offset)
    error_count, offset = _read_u32_list(data, offset)
    ber_mantissa, offset = _read_u32_list(data, offset)
    ber_exponent, offset = _read_s32_list(data, offset)
    if offset != len(data):
        raise ValueError(f"BER status parser consumed {offset} of {len(data)} bytes")

    return BerStatus(
        layout=layout,
        control=control,
        fec_on=fec_on,
        tx_mode=tx_mode,
        tx_rate=tx_rate,
        check_mode=check_mode,
        ppg_lock=ppg_lock,
        ed_lock=ed_lock,
        runtime_s=runtime_s,
        error_time=error_time,
        error_count=error_count,
        ber_mantissa=ber_mantissa,
        ber_exponent=ber_exponent,
        raw=data,
    )


class BerController:
    def __init__(
        self,
        port_name: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
        address: int = 0,
    ):
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.address = _u8(address, "address")
        self.serial = None

    def open(self) -> None:
        self.serial = serial.Serial(
            port=self.port_name,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        logger.info("Connected %s @ %s", self.port_name, self.baudrate)

    def close(self) -> None:
        if self.serial is not None and self.serial.is_open:
            self.serial.close()
            logger.info("Disconnected %s", self.port_name)

    def _ensure_open(self) -> None:
        if self.serial is None or not self.serial.is_open:
            raise RuntimeError("serial port is not open")

    def transact(self, command: int, data: bytes = b"") -> bytes:
        self._ensure_open()
        frame = build_frame(self.address, command, data)
        logger.debug("TX: %s", frame.hex(" ").upper())
        self.serial.reset_input_buffer()
        self.serial.write(frame)
        self.serial.flush()

        header = self.serial.read(4)
        if len(header) != 4:
            raise TimeoutError("timeout waiting for BER response header")
        length = int.from_bytes(header[2:4], "big")
        if length < 7:
            raise ValueError(f"invalid BER response length: {length}")
        remainder = self.serial.read(length - 4)
        if len(remainder) != length - 4:
            raise TimeoutError("timeout waiting for BER response body")
        response = header + remainder
        logger.debug("RX: %s", response.hex(" ").upper())
        return parse_response(response, self.address, command)

    def _status_command(self, command: int, data: bytes) -> BerStatus:
        return parse_status(self.transact(command, data))

    def query_status(self, chn: int = 0) -> BerStatus:
        chn = _u8(chn, "chn")
        return self._status_command(CMD_STATUS, bytes([chn]))

    def control(self, start: bool, chn: int = 0) -> BerStatus:
        chn = _u8(chn, "chn")
        return self._status_command(CMD_CONTROL, bytes([chn, 1 if start else 0]))

    def set_check_mode(self, mode: int, chn: int = 0) -> BerStatus:
        chn = _u8(chn, "chn")
        mode = _u8(mode, "check_mode")
        return self._status_command(CMD_CHECK_MODE, bytes([chn, mode]))

    def clear_errors(self, chn: int = 0) -> BerStatus:
        chn = _u8(chn, "chn")
        return self._status_command(CMD_CLEAR, bytes([chn]))

    def set_rate(self, rate: int, chn: int = 0) -> BerStatus:
        chn = _u8(chn, "chn")
        rate = _u8(rate, "rate")
        return self._status_command(CMD_RATE, bytes([chn, rate]))

    def set_prbs_mode(self, mode: int, chn: int = 0) -> BerStatus:
        chn = _u8(chn, "chn")
        mode = _u8(mode, "mode")
        return self._status_command(CMD_MODE, bytes([chn, mode]))

    def initialize(
        self,
        chn: int,
        mode: int,
        rate: int,
        check_mode: int,
        start: bool = True,
    ) -> BerStatus:
        logger.info(
            "BER init: chn=%s, mode=%s, rate=%s, check=%s",
            chn,
            PRBS_MODE_NAMES.get(mode, mode),
            RATE_NAMES.get(rate, rate),
            CHECK_MODE_NAMES.get(check_mode, check_mode),
        )
        self.set_prbs_mode(mode, chn)
        self.set_rate(rate, chn)
        self.set_check_mode(check_mode, chn)
        if start:
            self.control(True, chn)
        return self.clear_errors(chn)


def parse_int(text: str) -> int:
    value = text.strip()
    if value.lower().startswith("0x"):
        return int(value, 16)
    if any(character in "abcdefABCDEF" for character in value):
        return int(value, 16)
    return int(value)


def setup_style(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei", 10))
    style.configure("TFrame", background="#F0F2F5")
    style.configure("TLabelframe", background="#F0F2F5", borderwidth=1, relief="solid")
    style.configure(
        "TLabelframe.Label",
        background="#F0F2F5",
        font=("Microsoft YaHei", 10, "bold"),
    )
    style.configure("TLabel", background="#F0F2F5")
    style.configure("Primary.TButton", foreground="white", background="#0078D4")
    style.map("Primary.TButton", background=[("active", "#005A9E")])
    style.configure("Success.TButton", foreground="white", background="#107C41")
    style.map("Success.TButton", background=[("active", "#0B5930")])
    style.configure("Danger.TButton", foreground="white", background="#C42B1C")
    style.map("Danger.TButton", background=[("active", "#8F1F14")])


class GuiLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__(logging.DEBUG)
        self.callback = callback

    def emit(self, record) -> None:
        try:
            self.callback(record.getMessage())
        except Exception:
            pass


class BerToolApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.master = master
        self.controller: Optional[BerController] = None
        self.busy = False
        self.op_buttons: list[ttk.Button] = []

        setup_style(master)
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=0)
        self.rowconfigure(4, weight=1)

        self._build_connection_panel()
        self._build_config_panel()
        self._build_operation_panel()
        self._build_status_panel()
        self._build_log_panel()

        self._log_handler = GuiLogHandler(self.log)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._log_handler)
        logger.propagate = False

        self._set_operation_state(False)
        self.scan_ports()
        master.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_connection_panel(self) -> None:
        frame = ttk.LabelFrame(self, text=" 串口配置 ")
        frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for column in range(8):
            frame.columnconfigure(column, weight=1)

        ttk.Label(frame, text="COM 端口:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.port_combo = ttk.Combobox(frame, state="readonly", width=12)
        self.port_combo.grid(row=0, column=1, padx=5, pady=8, sticky="w")
        ttk.Button(frame, text="刷新", command=self.scan_ports).grid(row=0, column=2, padx=5)

        ttk.Label(frame, text="波特率:").grid(row=0, column=3, padx=5, sticky="e")
        self.baud_combo = ttk.Combobox(frame, values=BAUD_CHOICES, state="readonly", width=10)
        self.baud_combo.set("115200")
        self.baud_combo.grid(row=0, column=4, padx=5, sticky="w")

        ttk.Label(frame, text="业务板地址:").grid(row=0, column=5, padx=5, sticky="e")
        self.address_entry = ttk.Entry(frame, width=7)
        self.address_entry.insert(0, "0")
        self.address_entry.grid(row=0, column=6, padx=5, sticky="w")

        self.connect_button = ttk.Button(
            frame,
            text="连接串口",
            style="Primary.TButton",
            command=self.toggle_connection,
        )
        self.connect_button.grid(row=0, column=7, padx=10)

    def _build_config_panel(self) -> None:
        frame = ttk.LabelFrame(self, text=" TEC-100G BERT 配置 ")
        frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        for column in range(8):
            frame.columnconfigure(column, weight=1)

        ttk.Label(frame, text="PRBS 模式:").grid(row=0, column=0, padx=5, pady=7, sticky="e")
        self.mode_combo = ttk.Combobox(frame, values=list(PRBS_MODES), state="readonly", width=10)
        self.mode_combo.set("PRBS31")
        self.mode_combo.grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(frame, text="速率:").grid(row=0, column=2, padx=5, sticky="e")
        self.rate_combo = ttk.Combobox(frame, values=list(RATES), state="readonly", width=10)
        self.rate_combo.set("25.78G")
        self.rate_combo.grid(row=0, column=3, padx=5, sticky="w")

        ttk.Label(frame, text="检测模式:").grid(row=0, column=4, padx=5, sticky="e")
        self.check_combo = ttk.Combobox(frame, values=list(CHECK_MODES), state="readonly", width=10)
        self.check_combo.set("RATIO")
        self.check_combo.grid(row=0, column=5, padx=5, sticky="w")

        ttk.Label(frame, text="通道 chn:").grid(row=0, column=6, padx=5, sticky="e")
        self.chn_entry = ttk.Entry(frame, width=7)
        self.chn_entry.insert(0, "0")
        self.chn_entry.grid(row=0, column=7, padx=5, sticky="w")

    def _build_operation_panel(self) -> None:
        frame = ttk.LabelFrame(self, text=" 操作 ")
        frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        inner = ttk.Frame(frame)
        inner.pack(pady=8)

        definitions = [
            ("初始化并启动", self.op_initialize, "Success.TButton", 14),
            ("查询状态", self.op_query, "Primary.TButton", 12),
            ("启动", self.op_start, "TButton", 9),
            ("停止", self.op_stop, "Danger.TButton", 9),
            ("误码清零", self.op_clear, "TButton", 11),
        ]
        for column, (text, command, style, width) in enumerate(definitions):
            button = ttk.Button(inner, text=text, command=command, style=style, width=width)
            button.grid(row=0, column=column, padx=8)
            self.op_buttons.append(button)

    def _build_status_panel(self) -> None:
        frame = ttk.LabelFrame(self, text=" BER 状态 ")
        frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        frame.columnconfigure(0, weight=1)

        self.summary_label = ttk.Label(
            frame,
            text="控制/状态: -    FEC: -    模式: -    速率: -    检测: -    运行时间: -",
            font=("Microsoft YaHei", 10, "bold"),
            foreground="#0078D4",
        )
        self.summary_label.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
        self.layout_label = ttk.Label(frame, text="解析布局: -")
        self.layout_label.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 4))

        columns = ("lane", "ppg", "ed", "errors", "time", "ber")
        self.status_tree = ttk.Treeview(frame, columns=columns, show="headings", height=4)
        headings = {
            "lane": "通道",
            "ppg": "PPG 锁定",
            "ed": "ED 锁定",
            "errors": "误码数",
            "time": "误码计时",
            "ber": "误码率",
        }
        widths = {"lane": 65, "ppg": 100, "ed": 100, "errors": 140, "time": 140, "ber": 180}
        for column in columns:
            self.status_tree.heading(column, text=headings[column])
            self.status_tree.column(column, width=widths[column], anchor="center")
        for lane in range(4):
            self.status_tree.insert("", "end", iid=str(lane), values=(f"CH{lane}", "-", "-", "-", "-", "-"))
        self.status_tree.grid(row=2, column=0, sticky="ew", padx=8, pady=(2, 8))

    def _build_log_panel(self) -> None:
        frame = ttk.LabelFrame(self, text=" 报文日志 ")
        frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=5)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(
            frame,
            background="#1E1E1E",
            foreground="#D4D4D4",
            font=("Consolas", 10),
            height=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        ttk.Button(frame, text="清空日志", command=self.clear_log).grid(row=1, column=0, sticky="e", padx=5, pady=5)

    def scan_ports(self) -> None:
        ports = sorted(serial.tools.list_ports.comports())
        names = [port.device for port in ports]
        self.port_combo["values"] = names
        self.port_combo.set(names[0] if names else "")
        self.log(f"扫描完成，发现 {len(names)} 个可用端口")

    def log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}\n"
        self.after(0, lambda: self._append_log(line))

    def _append_log(self, line: str) -> None:
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    def clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)

    def is_connected(self) -> bool:
        return bool(
            self.controller is not None
            and self.controller.serial is not None
            and self.controller.serial.is_open
        )

    def _set_operation_state(self, connected: bool) -> None:
        state = "normal" if connected and not self.busy else "disabled"
        for button in self.op_buttons:
            button.configure(state=state)

    def toggle_connection(self) -> None:
        if self.is_connected():
            self.controller.close()
            self.controller = None
            self.connect_button.configure(text="连接串口", style="Primary.TButton")
            self._set_operation_state(False)
            return
        if not self.port_combo.get():
            messagebox.showwarning("串口", "请选择串口")
            return
        try:
            self.controller = BerController(
                self.port_combo.get(),
                baudrate=int(self.baud_combo.get()),
                address=_u8(parse_int(self.address_entry.get()), "address"),
            )
            self.controller.open()
            self.connect_button.configure(text="断开连接", style="Success.TButton")
            self._set_operation_state(True)
        except Exception as exc:
            self.controller = None
            self.log(f"连接失败: {exc}")
            messagebox.showerror("串口错误", str(exc))

    def _parameters(self) -> tuple[int, int, int, int]:
        chn = _u8(parse_int(self.chn_entry.get()), "chn")
        return (
            chn,
            PRBS_MODES[self.mode_combo.get()],
            RATES[self.rate_combo.get()],
            CHECK_MODES[self.check_combo.get()],
        )

    def _run(self, name: str, function) -> None:
        if not self.is_connected() or self.busy:
            return
        try:
            self.controller.address = _u8(parse_int(self.address_entry.get()), "address")
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self.busy = True
        self._set_operation_state(True)
        self.connect_button.configure(state="disabled")

        def worker():
            try:
                result = function(self.controller)
                self.after(0, lambda: self._finish(name, result, None))
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: self._finish(name, None, error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, name: str, status: Optional[BerStatus], error: Optional[str]) -> None:
        self.busy = False
        self.connect_button.configure(state="normal")
        self._set_operation_state(self.is_connected())
        if error is not None:
            self.log(f"{name} 失败: {error}")
            messagebox.showerror("BER 操作失败", error)
            return
        self.log(f"{name} 通信完成")
        if status is not None:
            self.render_status(status)

    def op_initialize(self) -> None:
        try:
            chn, mode, rate, check = self._parameters()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._run("BER 初始化", lambda controller: controller.initialize(chn, mode, rate, check))

    def op_query(self) -> None:
        try:
            chn, _mode, _rate, _check = self._parameters()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._run("状态查询", lambda controller: controller.query_status(chn))

    def op_start(self) -> None:
        try:
            chn, _mode, _rate, _check = self._parameters()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._run("启动 PRBS", lambda controller: controller.control(True, chn))

    def op_stop(self) -> None:
        try:
            chn, _mode, _rate, _check = self._parameters()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._run("停止 PRBS", lambda controller: controller.control(False, chn))

    def op_clear(self) -> None:
        try:
            chn, _mode, _rate, _check = self._parameters()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._run("误码清零", lambda controller: controller.clear_errors(chn))

    def render_status(self, status: BerStatus) -> None:
        control_text = f"{status.control}（按文档={'启动' if status.control == 1 else '停止' if status.control == 0 else '未知'}）"
        fec_text = "N/A" if status.fec_on is None else ("开" if status.fec_on else "关")
        summary = (
            f"控制/状态原始值: {control_text}    FEC: {fec_text}    "
            f"模式: {PRBS_MODE_NAMES.get(status.tx_mode, status.tx_mode)}    "
            f"速率: {RATE_NAMES.get(status.tx_rate, status.tx_rate)}    "
            f"检测: {CHECK_MODE_NAMES.get(status.check_mode, status.check_mode)}    "
            f"运行时间: {status.runtime_s} s"
        )
        self.summary_label.configure(text=summary)
        layout_name = "真机80字节" if status.layout == "observed80" else "文档81字节"
        self.layout_label.configure(text=f"解析布局: {layout_name}；原始首字节语义需结合固件确认")
        ber_values = status.ber_strings()
        for lane in range(4):
            self.status_tree.item(
                str(lane),
                values=(
                    f"CH{lane}",
                    "锁定" if status.ppg_lock[lane] else "失锁",
                    "锁定" if status.ed_lock[lane] else "失锁",
                    status.error_count[lane],
                    status.error_time[lane],
                    ber_values[lane],
                ),
            )

    def on_close(self) -> None:
        if self.is_connected():
            self.controller.close()
        logger.removeHandler(self._log_handler)
        self.master.destroy()


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    root.title("JTT1031/1030 TEC-100G BERT Test Tool")
    root.geometry("980x760")
    root.minsize(900, 680)
    BerToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
