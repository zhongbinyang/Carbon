#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Standalone TCB TEC ASCII (V2.05) control tool."""

import logging
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import serial
import serial.tools.list_ports

logger = logging.getLogger("TCB_TEC_ASCII")

_TIMEOUT_HINT = (
    "check serial port, baud rate (9600), board power/online, "
    "and that auto-send was stopped (T0/SC)"
)


def format_set_temp(celsius):
    return "S1" + f"{float(celsius):.1f}"


def _strip_line(line):
    return line.strip().strip("\r").strip("\n")


def parse_pv(line):
    s = _strip_line(line)
    if not s.upper().startswith("P"):
        raise ValueError(f"bad PV response: {line!r}")
    return float(s[1:])


def parse_sv(line):
    s = _strip_line(line)
    if not s.upper().startswith("S"):
        raise ValueError(f"bad SV response: {line!r}")
    return float(s[1:])


def parse_duty(line):
    s = _strip_line(line)
    if not s.upper().startswith("D"):
        raise ValueError(f"bad duty response: {line!r}")
    return int(float(s[1:]))


def parse_ready(line):
    s = _strip_line(line).upper()
    if s == "R1":
        return True
    if s == "R0":
        return False
    raise ValueError(f"bad ready response: {line!r}")


def parse_alarm(line):
    s = _strip_line(line)
    if not s.upper().startswith("E"):
        raise ValueError(f"bad alarm response: {line!r}")
    return s.upper() if s[0] in "eE" else s


def parse_tec_enable(line):
    s = _strip_line(line)
    if s == "1":
        return True
    if s == "0":
        return False
    raise ValueError(f"bad TEC enable response: {line!r}")


class TecAsciiController:
    def __init__(self, port_name, baudrate=9600, timeout=1.0):
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None

    def open(self):
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
        # Drain any leftover auto-send junk briefly
        time.sleep(0.05)
        self.serial.reset_input_buffer()
        self.transact("T0")
        self.transact("SC")

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    def _ensure_open(self):
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("serial not open")

    def transact(self, command):
        self._ensure_open()
        cmd = command.strip().upper()
        payload = (cmd + "\r\n").encode("ascii")
        logger.debug("TX: %s", cmd)
        self.serial.reset_input_buffer()
        self.serial.write(payload)
        self.serial.flush()

        deadline = time.time() + self.timeout
        buf = bytearray()
        while time.time() < deadline:
            chunk = self.serial.read(1)
            if not chunk:
                continue
            buf.extend(chunk)
            if buf.endswith(b"\r\n"):
                line = buf[:-2].decode("ascii", errors="replace")
                logger.debug("RX: %s", line)
                return line.strip()
        raise TimeoutError(
            f"timeout waiting response for {cmd!r}; {_TIMEOUT_HINT}"
        )

    def set_temp(self, celsius):
        resp = self.transact(format_set_temp(celsius))
        if resp.strip().upper() != "OK":
            raise ValueError(f"set temp failed: {resp!r}")

    def set_tec_enable(self, on):
        resp = self.transact("SEN1" if on else "SEN0")
        expect = "TEC Enabled!" if on else "TEC Disabled!"
        if expect.lower() not in resp.lower():
            raise ValueError(f"TEC enable failed: {resp!r}")

    def status(self):
        return {
            "pv": parse_pv(self.transact("RP1")),
            "sv": parse_sv(self.transact("RS1")),
            "duty": parse_duty(self.transact("RD")),
            "ready": parse_ready(self.transact("RR")),
            "alarm": parse_alarm(self.transact("RE")),
            "tec_on": parse_tec_enable(self.transact("REN")),
        }


BAUD_CHOICES = ["9600", "19200", "38400", "57600", "115200"]
REFRESH_INTERVALS = ["1", "2", "5", "10"]


class GuiLogHandler(logging.Handler):
    def __init__(self, log_func):
        super().__init__(level=logging.DEBUG)
        self.log_func = log_func

    def emit(self, record):
        try:
            self.log_func(record.getMessage())
        except Exception:
            pass


class TecAsciiApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.controller = None
        self.busy = False
        self.op_buttons = []
        self._auto_refresh_job = None

        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._build_conn_panel()
        self._build_control_panel()
        self._build_status_panel()
        self._build_log_panel()

        logger.setLevel(logging.DEBUG)
        self._log_handler = GuiLogHandler(self.log)
        logger.addHandler(self._log_handler)
        logger.propagate = False

        self._update_btn_states(False)
        self.scan_ports()
        master.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_conn_panel(self):
        frame = ttk.LabelFrame(self, text=" 连接 ")
        frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for i in range(7):
            frame.columnconfigure(i, weight=1)

        ttk.Label(frame, text="COM 端口:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.port_combo = ttk.Combobox(frame, state="readonly", width=12)
        self.port_combo.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        self.btn_refresh = ttk.Button(frame, text="刷新", width=6, command=self.scan_ports)
        self.btn_refresh.grid(row=0, column=2, padx=5, pady=8, sticky="w")

        ttk.Label(frame, text="波特率:").grid(row=0, column=3, padx=5, pady=8, sticky="e")
        self.baud_combo = ttk.Combobox(frame, values=BAUD_CHOICES, state="readonly", width=10)
        self.baud_combo.set("9600")
        self.baud_combo.grid(row=0, column=4, padx=5, pady=8, sticky="w")

        self.btn_connect = ttk.Button(frame, text="连接", command=self.toggle_connection)
        self.btn_connect.grid(row=0, column=5, padx=10, pady=8, sticky="e")

    def _build_control_panel(self):
        frame = ttk.LabelFrame(self, text=" 控制 ")
        frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="目标温度 (°C):").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.entry_temp = ttk.Entry(frame, width=10)
        self.entry_temp.insert(0, "25.0")
        self.entry_temp.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=4, pady=8)

        self.btn_set_temp = ttk.Button(
            btn_frame, text="设定温度", width=12, command=self.op_set_temp
        )
        self.btn_set_temp.grid(row=0, column=0, padx=8)
        self.op_buttons.append(self.btn_set_temp)

        self.btn_tec_on = ttk.Button(btn_frame, text="TEC 开", width=12, command=self.op_tec_on)
        self.btn_tec_on.grid(row=0, column=1, padx=8)
        self.op_buttons.append(self.btn_tec_on)

        self.btn_tec_off = ttk.Button(btn_frame, text="TEC 关", width=12, command=self.op_tec_off)
        self.btn_tec_off.grid(row=0, column=2, padx=8)
        self.op_buttons.append(self.btn_tec_off)

        self.btn_read_status = ttk.Button(
            btn_frame, text="读取状态", width=12, command=self.op_read_status
        )
        self.btn_read_status.grid(row=0, column=3, padx=8)
        self.op_buttons.append(self.btn_read_status)

        refresh_frame = ttk.Frame(frame)
        refresh_frame.grid(row=2, column=0, columnspan=4, pady=4)
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.chk_auto_refresh = ttk.Checkbutton(
            refresh_frame,
            text="自动刷新",
            variable=self.auto_refresh_var,
            command=self._on_auto_refresh_toggle,
        )
        self.chk_auto_refresh.pack(side="left", padx=8)
        ttk.Label(refresh_frame, text="间隔 (秒):").pack(side="left", padx=(8, 4))
        self.interval_combo = ttk.Combobox(
            refresh_frame, values=REFRESH_INTERVALS, state="readonly", width=4
        )
        self.interval_combo.set("2")
        self.interval_combo.pack(side="left", padx=4)
        self.interval_combo.bind("<<ComboboxSelected>>", lambda _e: self._restart_auto_refresh())

    def _build_status_panel(self):
        frame = ttk.LabelFrame(self, text=" 状态 ")
        frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        for col in range(6):
            frame.columnconfigure(col, weight=1)

        labels = [
            ("PV (°C):", "lbl_pv"),
            ("SV (°C):", "lbl_sv"),
            ("占空比:", "lbl_duty"),
            ("就绪:", "lbl_ready"),
            ("报警:", "lbl_alarm"),
            ("TEC 使能:", "lbl_tec"),
        ]
        for idx, (text, attr) in enumerate(labels):
            ttk.Label(frame, text=text).grid(row=0, column=idx * 2, padx=5, pady=8, sticky="e")
            lbl = ttk.Label(frame, text="-", font=("Consolas", 10, "bold"))
            lbl.grid(row=0, column=idx * 2 + 1, padx=5, pady=8, sticky="w")
            setattr(self, attr, lbl)

    def _build_log_panel(self):
        frame = ttk.LabelFrame(self, text=" 通信日志 ")
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

    def is_connected(self):
        return (
            self.controller is not None
            and self.controller.serial is not None
            and self.controller.serial.is_open
        )

    def _update_btn_states(self, connected):
        if self.busy:
            state = "disabled"
        else:
            state = "normal" if connected else "disabled"
        for btn in self.op_buttons:
            btn.config(state=state)

    def _update_status_labels(self, info):
        self.lbl_pv.config(text=f"{info['pv']:.2f}")
        self.lbl_sv.config(text=f"{info['sv']:.2f}")
        self.lbl_duty.config(text=str(info["duty"]))
        self.lbl_ready.config(text="是" if info["ready"] else "否")
        self.lbl_alarm.config(text=info["alarm"])
        self.lbl_tec.config(text="开" if info["tec_on"] else "关")

    def toggle_connection(self):
        if self.is_connected():
            self._stop_auto_refresh()
            self.controller.close()
            self.controller = None
            self.btn_connect.config(text="连接")
            self._update_btn_states(False)
            self.log("串口连接已断开")
        else:
            port = self.port_combo.get()
            baud = self.baud_combo.get()
            if not port:
                messagebox.showwarning("警告", "请先选择一个串口端口！")
                return
            try:
                self.controller = TecAsciiController(port, baudrate=int(baud))
                self.controller.open()
                self.btn_connect.config(text="断开")
                self._update_btn_states(True)
                self.log(f"已连接 {port} @ {baud} (T0+SC 已发送)")
                self._restart_auto_refresh()
            except Exception as exc:
                self.controller = None
                messagebox.showerror(
                    "串口错误",
                    f"无法连接到该串口，可能被其他程序占用。\n错误信息: {exc}",
                )
                self.log(f"连接失败: {exc}")

    def start_op(self, op_name, func):
        if not self.is_connected():
            return
        if self.busy:
            self.log(f"上一操作尚未完成，忽略: {op_name}")
            return

        self.busy = True
        self._update_btn_states(False)
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
            self._update_btn_states(True)
        if result is not None:
            self._update_status_labels(result)
        if not op_name.startswith("自动刷新"):
            self.log(f"{op_name} 完成")

    def _on_op_error(self, op_name, err_msg):
        self.busy = False
        self.btn_connect.config(state="normal")
        if self.is_connected():
            self._update_btn_states(True)
        self.log(f"{op_name} 失败: {err_msg}")
        if not op_name.startswith("自动刷新"):
            messagebox.showerror("操作故障", f"{op_name} 失败: {err_msg}")

    def op_set_temp(self):
        try:
            temp = float(self.entry_temp.get().strip())
        except ValueError:
            messagebox.showerror("参数错误", "目标温度必须是数字")
            return

        def do(controller):
            controller.set_temp(temp)
            return controller.status()

        self.start_op("设定温度", do)

    def op_tec_on(self):
        def do(controller):
            controller.set_tec_enable(True)
            return controller.status()

        self.start_op("TEC 开", do)

    def op_tec_off(self):
        def do(controller):
            controller.set_tec_enable(False)
            return controller.status()

        self.start_op("TEC 关", do)

    def op_read_status(self):
        def do(controller):
            return controller.status()

        self.start_op("读取状态", do)

    def _on_auto_refresh_toggle(self):
        if self.auto_refresh_var.get():
            self._restart_auto_refresh()
        else:
            self._stop_auto_refresh()

    def _stop_auto_refresh(self):
        if self._auto_refresh_job is not None:
            self.after_cancel(self._auto_refresh_job)
            self._auto_refresh_job = None

    def _restart_auto_refresh(self):
        self._stop_auto_refresh()
        if self.auto_refresh_var.get() and self.is_connected():
            self._schedule_auto_refresh_tick()

    def _schedule_auto_refresh_tick(self):
        if not self.auto_refresh_var.get() or not self.is_connected():
            return
        try:
            interval_ms = int(self.interval_combo.get()) * 1000
        except ValueError:
            interval_ms = 2000

        def tick():
            self._auto_refresh_job = None
            if not self.auto_refresh_var.get() or not self.is_connected():
                return
            if not self.busy:
                self.start_op("自动刷新", lambda controller: controller.status())
            self._auto_refresh_job = self.after(interval_ms, tick)

        self._auto_refresh_job = self.after(interval_ms, tick)

    def on_close(self):
        self._stop_auto_refresh()
        if self.is_connected():
            self.controller.close()
        self.controller = None
        logger.removeHandler(self._log_handler)
        self.master.destroy()


def main():
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    root.title("TCB TEC ASCII Tool (V2.05)")
    root.geometry("780x640")
    TecAsciiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
