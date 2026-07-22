#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Standalone JTT1031 register-mode (0x0016/0x0017) serial test tool."""

import logging
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import serial
import serial.tools.list_ports

logger = logging.getLogger("JTT1031_REG")

CMD_READ = 0x0016
CMD_WRITE = 0x0017

BAUD_CHOICES = ["9600", "19200", "38400", "57600", "115200"]


def checksum(data):
    return sum(data) & 0xFF


def build_frame(address, command, data=b""):
    data = bytes(data or b"")
    length = 7 + len(data)
    frame = bytearray([
        0xA5,
        address & 0xFF,
        (length >> 8) & 0xFF,
        length & 0xFF,
        (command >> 8) & 0xFF,
        command & 0xFF,
    ])
    frame.extend(data)
    frame.append(checksum(frame))
    return bytes(frame)


def parse_response(frame, expect_address, expect_command):
    if len(frame) < 7:
        raise ValueError("response too short")
    if frame[0] != 0x5A:
        raise ValueError(f"bad head: 0x{frame[0]:02X}")
    if frame[1] != (expect_address & 0xFF):
        raise ValueError("address mismatch")
    length = (frame[2] << 8) | frame[3]
    if length != len(frame):
        raise ValueError("length mismatch")
    if checksum(frame[:-1]) != frame[-1]:
        raise ValueError("checksum error")
    command = (frame[4] << 8) | frame[5]
    if command != expect_command:
        raise ValueError("command mismatch")
    return frame[6:-1]


def parse_int(text):
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if any(ch in "abcdefABCDEF" for ch in text):
        return int(text, 16)
    return int(text)


def parse_hex_bytes(text):
    raw = text.replace(",", " ").replace("0x", "").replace("0X", "")
    parts = raw.split()
    if not parts:
        raise ValueError("write data cannot be empty")
    return bytes(int(p, 16) for p in parts)


class RegController:
    def __init__(self, port_name, baudrate=115200, timeout=1.0, address=0):
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.address = address
        self.serial = None

    def open(self):
        self.serial = serial.Serial(
            port=self.port_name,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    def _ensure_open(self):
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("serial not open")

    def _transact(self, command, data=b""):
        self._ensure_open()
        frame = build_frame(self.address, command, data)
        logger.debug("TX: %s", frame.hex(" ").upper())
        self.serial.reset_input_buffer()
        self.serial.write(frame)
        self.serial.flush()

        header = self.serial.read(4)
        if len(header) < 4:
            raise TimeoutError("timeout waiting response header")
        length = (header[2] << 8) | header[3]
        if length < 7:
            raise ValueError("response length too short")
        rest = self.serial.read(length - 4)
        if len(rest) < length - 4:
            raise TimeoutError("timeout waiting response body")
        response = header + rest
        logger.debug("RX: %s", response.hex(" ").upper())
        return parse_response(response, self.address, command)

    def read_register(self, port, dev_address, start_reg, size):
        if not 1 <= size <= 128:
            raise ValueError("size must be 1..128")
        payload = self._transact(CMD_READ, bytes([port, dev_address, start_reg, size]))
        if len(payload) < 5 + size:
            raise ValueError("0x0016 response too short")
        state, r_port, r_dev, r_start, r_size = payload[:5]
        if state != 1:
            raise ValueError(f"invalid state: {state}")
        if (r_port, r_dev, r_start, r_size) != (port, dev_address, start_reg, size):
            raise ValueError("0x0016 echo mismatch")
        return payload[5:5 + size]

    def write_register(self, port, dev_address, start_reg, data):
        data = bytes(data)
        if not 1 <= len(data) <= 128:
            raise ValueError("data length must be 1..128")
        payload = self._transact(
            CMD_WRITE,
            bytes([port, dev_address, start_reg, len(data)]) + data,
        )
        if len(payload) < 5:
            raise ValueError("0x0017 response too short")
        state, r_port, r_dev, r_start, r_size = payload[:5]
        if state != 1:
            raise ValueError(f"invalid state: {state}")
        if (r_port, r_dev, r_start, r_size) != (port, dev_address, start_reg, len(data)):
            raise ValueError("0x0017 echo mismatch")


def setup_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei", 10))
    style.configure("TFrame", background="#F0F2F5")
    style.configure("TLabelframe", background="#F0F2F5", borderwidth=1, relief="solid")
    style.configure(
        "TLabelframe.Label",
        background="#F0F2F5",
        font=("Microsoft YaHei", 10, "bold"),
        foreground="#333333",
    )
    style.configure("TLabel", background="#F0F2F5", foreground="#444444")
    style.configure("TButton", font=("Microsoft YaHei", 10), padding=4)
    style.configure("Primary.TButton", font=("Microsoft YaHei", 10, "bold"), foreground="white", background="#0078D4")
    style.map("Primary.TButton", background=[("active", "#005A9E"), ("disabled", "#CCE4F6")])
    style.configure("Success.TButton", font=("Microsoft YaHei", 10, "bold"), foreground="white", background="#107C41")
    style.map("Success.TButton", background=[("active", "#0B5930"), ("disabled", "#C5E3D3")])


class GuiLogHandler(logging.Handler):
    def __init__(self, log_func):
        super().__init__(level=logging.DEBUG)
        self.log_func = log_func

    def emit(self, record):
        try:
            self.log_func(record.getMessage())
        except Exception:
            pass


class RegToolApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.controller = None
        self.busy = False
        self.op_buttons = []

        setup_style(master)
        self.pack(fill="both", expand=True)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=1)

        self._build_conn_panel()
        self._build_param_panel()
        self._build_action_panel()
        self._build_log_panel()

        logger.setLevel(logging.DEBUG)
        logger.addHandler(GuiLogHandler(self.log))
        logger.propagate = False

        self.update_btn_states(False)
        self.scan_ports()

        master.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_conn_panel(self):
        frame = ttk.LabelFrame(self, text=" 串口配置 ")
        frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for i in range(8):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="COM 端口:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.port_combo = ttk.Combobox(frame, state="readonly", width=12)
        self.port_combo.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        self.btn_refresh = ttk.Button(frame, text="刷新", width=6, command=self.scan_ports)
        self.btn_refresh.grid(row=0, column=2, padx=5, pady=8, sticky="w")

        ttk.Label(frame, text="波特率:").grid(row=0, column=3, padx=5, pady=8, sticky="e")
        self.baud_combo = ttk.Combobox(frame, values=BAUD_CHOICES, state="readonly", width=10)
        self.baud_combo.set("115200")
        self.baud_combo.grid(row=0, column=4, padx=5, pady=8, sticky="w")

        ttk.Label(frame, text="业务板地址:").grid(row=0, column=5, padx=5, pady=8, sticky="e")
        self.entry_address = ttk.Entry(frame, width=6)
        self.entry_address.insert(0, "0")
        self.entry_address.grid(row=0, column=6, padx=5, pady=8, sticky="w")

        self.btn_connect = ttk.Button(
            frame, text="连接串口", style="Primary.TButton", command=self.toggle_connection
        )
        self.btn_connect.grid(row=0, column=7, padx=10, pady=8, sticky="e")

    def _build_param_panel(self):
        frame = ttk.LabelFrame(self, text=" 寄存器参数 ")
        frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        for col in range(8):
            frame.columnconfigure(col, weight=1)

        ttk.Label(frame, text="光模块端口:").grid(row=0, column=0, padx=5, pady=6, sticky="e")
        self.entry_port = ttk.Entry(frame, width=10)
        self.entry_port.insert(0, "0")
        self.entry_port.grid(row=0, column=1, padx=5, pady=6, sticky="w")

        ttk.Label(frame, text="器件地址:").grid(row=0, column=2, padx=5, pady=6, sticky="e")
        self.entry_dev = ttk.Entry(frame, width=10)
        self.entry_dev.insert(0, "A0")
        self.entry_dev.grid(row=0, column=3, padx=5, pady=6, sticky="w")

        ttk.Label(frame, text="起始寄存器:").grid(row=0, column=4, padx=5, pady=6, sticky="e")
        self.entry_start = ttk.Entry(frame, width=10)
        self.entry_start.insert(0, "00")
        self.entry_start.grid(row=0, column=5, padx=5, pady=6, sticky="w")

        ttk.Label(frame, text="读长度:").grid(row=0, column=6, padx=5, pady=6, sticky="e")
        self.entry_size = ttk.Entry(frame, width=10)
        self.entry_size.insert(0, "16")
        self.entry_size.grid(row=0, column=7, padx=5, pady=6, sticky="w")

    def _build_action_panel(self):
        frame = ttk.LabelFrame(self, text=" 操作 ")
        frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="写数据 (Hex):").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.entry_write_data = ttk.Entry(frame)
        self.entry_write_data.insert(0, "11 22 33 44")
        self.entry_write_data.grid(row=0, column=1, columnspan=2, padx=5, pady=8, sticky="ew")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=3, pady=8)
        self.btn_read = ttk.Button(
            btn_frame, text="读 (0x0016)", style="Primary.TButton", width=18, command=self.op_read
        )
        self.btn_read.grid(row=0, column=0, padx=15)
        self.op_buttons.append(self.btn_read)
        self.btn_write = ttk.Button(
            btn_frame, text="写 (0x0017)", style="Success.TButton", width=18, command=self.op_write
        )
        self.btn_write.grid(row=0, column=1, padx=15)
        self.op_buttons.append(self.btn_write)

        result_frame = ttk.Frame(frame)
        result_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=2)
        ttk.Label(result_frame, text="HEX:", font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=5)
        self.lbl_read_hex = ttk.Label(
            result_frame, text="-", font=("Consolas", 10, "bold"), foreground="#0078D4"
        )
        self.lbl_read_hex.pack(side="left", padx=5)
        ttk.Label(result_frame, text="ASCII:", font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=5)
        self.lbl_read_ascii = ttk.Label(
            result_frame, text="-", font=("Consolas", 10, "bold"), foreground="#107C41"
        )
        self.lbl_read_ascii.pack(side="left", padx=5)
        self.lbl_write_status = ttk.Label(frame, text="-", foreground="#107C41")
        self.lbl_write_status.grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=5)

    def _build_log_panel(self):
        frame = ttk.LabelFrame(self, text=" 报文日志 ")
        frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=5)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            frame, background="#1E1E1E", foreground="#D4D4D4", font=("Consolas", 10), height=12
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        btn_clear = ttk.Button(frame, text="清空日志", command=self.clear_logs)
        btn_clear.grid(row=1, column=0, sticky="e", padx=5, pady=5)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        self.after(0, lambda: self._insert_log(formatted))

    def _insert_log(self, formatted):
        self.log_text.insert(tk.END, formatted)
        self.log_text.see(tk.END)

    def clear_logs(self):
        self.log_text.delete("1.0", tk.END)

    def scan_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.port_combo["values"] = port_list
        if port_list:
            self.port_combo.set(port_list[0])
            self.log(f"扫描完成，发现 {len(port_list)} 个可用端口")
        else:
            self.port_combo.set("")
            self.log("没有发现可用串口，请检查硬件连接")

    def _get_board_address(self):
        return parse_int(self.entry_address.get())

    def is_connected(self):
        return (
            self.controller is not None
            and self.controller.serial is not None
            and self.controller.serial.is_open
        )

    def update_btn_states(self, connected):
        if self.busy:
            state = "disabled"
        else:
            state = "normal" if connected else "disabled"
        for btn in self.op_buttons:
            btn.config(state=state)

    def toggle_connection(self):
        if self.is_connected():
            self.controller.close()
            self.controller = None
            self.btn_connect.config(text="连接串口", style="Primary.TButton")
            self.update_btn_states(False)
            self.log("串口连接已断开")
        else:
            port = self.port_combo.get()
            baud = self.baud_combo.get()
            if not port:
                messagebox.showwarning("警告", "请先选择一个串口端口！")
                return
            try:
                address = self._get_board_address()
                self.controller = RegController(port, baudrate=int(baud), address=address)
                self.controller.open()
                self.btn_connect.config(text="断开连接", style="Success.TButton")
                self.update_btn_states(True)
                self.log(f"已连接 {port} @ {baud}, 业务板地址 {address}")
            except Exception as exc:
                self.controller = None
                messagebox.showerror(
                    "串口错误",
                    f"无法连接到该串口，可能被其他程序占用。\n错误信息: {exc}",
                )
                self.log(f"连接失败: {exc}")

    def _read_params(self):
        port = parse_int(self.entry_port.get())
        dev_address = parse_int(self.entry_dev.get())
        start_reg = parse_int(self.entry_start.get())
        size = int(self.entry_size.get())
        return port, dev_address, start_reg, size

    def start_op(self, op_name, func):
        if not self.is_connected():
            return
        if self.busy:
            self.log(f"上一操作尚未完成，忽略: {op_name}")
            return
        try:
            self.controller.address = self._get_board_address()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.busy = True
        self.update_btn_states(False)
        self.btn_connect.config(state="disabled")

        def worker():
            try:
                result = func(self.controller)
                self.after(0, lambda: self._on_op_success(op_name, result))
            except Exception as exc:
                err_msg = str(exc)
                self.after(0, lambda: self._on_op_error(op_name, err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_op_success(self, op_name, result):
        self.busy = False
        self.btn_connect.config(state="normal")
        if self.is_connected():
            self.update_btn_states(True)
        self.log(f"{op_name} 完成")
        if result is not None:
            self._render_result(result)

    def _on_op_error(self, op_name, err_msg):
        self.busy = False
        self.btn_connect.config(state="normal")
        if self.is_connected():
            self.update_btn_states(True)
        self.log(f"{op_name} 失败: {err_msg}")
        messagebox.showerror("操作故障", f"{op_name} 失败: {err_msg}")

    def _render_result(self, result):
        kind, payload = result
        if kind == "read":
            self.lbl_read_hex.config(text=payload.hex(" ").upper() or "(empty)")
            self.lbl_read_ascii.config(
                text=payload.decode("ascii", errors="replace").replace("\r", " ").replace("\n", " ")
            )
        elif kind == "write":
            self.lbl_write_status.config(text=f"Write OK: {payload} byte(s)")

    def op_read(self):
        try:
            port, dev_address, start_reg, size = self._read_params()
            if not 1 <= size <= 128:
                raise ValueError("read length must be 1..128")
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.lbl_read_hex.config(text="Reading...")
        self.lbl_read_ascii.config(text="")

        def do(controller):
            data = controller.read_register(
                port=port,
                dev_address=dev_address,
                start_reg=start_reg,
                size=size,
            )
            return ("read", data)

        self.start_op("JTT1031 register read", do)

    def op_write(self):
        try:
            port, dev_address, start_reg, _size = self._read_params()
            data = parse_hex_bytes(self.entry_write_data.get())
            if not 1 <= len(data) <= 128:
                raise ValueError("write length must be 1..128")
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        def do(controller):
            controller.write_register(
                port=port,
                dev_address=dev_address,
                start_reg=start_reg,
                data=data,
            )
            return ("write", len(data))

        self.start_op("JTT1031 register write", do)

    def on_close(self):
        if self.is_connected():
            self.controller.close()
            self.controller = None
        self.master.destroy()


def main():
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    root.title("JTT1031 Register Tool (0x0016 / 0x0017)")
    root.geometry("780x640")
    RegToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
