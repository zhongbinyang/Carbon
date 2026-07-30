#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Carbon ToolBox 页面框架
BasePage 提供所有工具页共享的能力: 串口连接面板、报文日志面板、
start_op 后台线程操作模式 (busy 防并发)、自动刷新循环。
新增工具页 = 继承 BasePage + 在 carbon_toolbox.PAGES 注册表加一行。
"""

import time
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial.tools.list_ports

BAUD_CHOICES = ["9600", "19200", "38400", "57600", "115200"]


def setup_style(root):
    """全局 ttk 样式，只在主窗口配置一次 (从原三个独立 GUI 收编)"""
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Microsoft YaHei', 10))
    style.configure('TFrame', background='#F0F2F5')
    style.configure('TLabelframe', background='#F0F2F5', borderwidth=1, relief='solid')
    style.configure('TLabelframe.Label', background='#F0F2F5', font=('Microsoft YaHei', 10, 'bold'), foreground='#333333')
    style.configure('TLabel', background='#F0F2F5', foreground='#444444')
    style.configure('TCheckbutton', background='#F0F2F5')
    style.configure('TButton', font=('Microsoft YaHei', 10), padding=4)
    style.configure('Primary.TButton', font=('Microsoft YaHei', 10, 'bold'), foreground='white', background='#0078D4')
    style.map('Primary.TButton', background=[('active', '#005A9E'), ('disabled', '#CCE4F6')])
    style.configure('Success.TButton', font=('Microsoft YaHei', 10, 'bold'), foreground='white', background='#107C41')
    style.map('Success.TButton', background=[('active', '#0B5930'), ('disabled', '#C5E3D3')])
    style.configure('Danger.TButton', font=('Microsoft YaHei', 10, 'bold'), foreground='white', background='#C42B1C')
    style.map('Danger.TButton', background=[('active', '#8F1F14'), ('disabled', '#F1C8C4')])


class GuiLogHandler(logging.Handler):
    """把协议模块的日志 (含 DEBUG 级收发报文) 转发到页面日志框"""
    def __init__(self, log_func):
        super().__init__(level=logging.DEBUG)
        self.log_func = log_func

    def emit(self, record):
        try:
            self.log_func(record.getMessage())
        except Exception:
            pass


class BasePage(ttk.Frame):
    """工具页基类。子类通过类属性声明连接面板配置，实现 build_body /
    create_controller，可选实现 render_result / on_auto_refresh。"""

    # ---- 子类通过类属性声明 ----
    default_baud = "115200"
    show_address = False
    address_label = "地址:"
    default_address = "0"
    bridge_logger = None        # 要桥接到日志框的 logging.Logger

    def __init__(self, notebook):
        super().__init__(notebook)
        self.controller = None
        self.busy = False
        self.op_buttons = []     # 子类把随连接状态启停的按钮加进来
        self.auto_var = None     # build_auto_refresh 后才存在

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)   # body 区
        self.rowconfigure(2, weight=1)   # 日志区

        self._build_conn_panel()
        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        self.build_body(body)
        self._build_log_panel()

        if self.bridge_logger is not None:
            self.bridge_logger.setLevel(logging.DEBUG)
            self.bridge_logger.addHandler(GuiLogHandler(self.log))
            # 日志只进页面日志框, 不再向根 logger 传播 (避免开发运行时控制台重复输出)
            self.bridge_logger.propagate = False

        self.update_btn_states(False)
        self.scan_ports()

    # ==================== 子类钩子 ====================

    def build_body(self, parent):
        """子类在 parent 里搭自己的参数/操作/状态区"""
        raise NotImplementedError

    def create_controller(self, port, baud, address):
        """子类创建协议控制器 (需有 open()/close()/serial 属性)"""
        raise NotImplementedError

    def render_result(self, result):
        """start_op 成功后主线程回调 (result 为 None 时不调用)"""
        pass

    def on_auto_refresh(self):
        """自动刷新 tick (主线程)。子类在此取参并发起 silent start_op"""
        pass

    # ==================== 串口连接面板 ====================

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
        self.baud_combo.set(self.default_baud)
        self.baud_combo.grid(row=0, column=4, padx=5, pady=8, sticky="w")

        if self.show_address:
            ttk.Label(frame, text=self.address_label).grid(row=0, column=5, padx=5, pady=8, sticky="e")
            self.entry_address = ttk.Entry(frame, width=6)
            self.entry_address.insert(0, self.default_address)
            self.entry_address.grid(row=0, column=6, padx=5, pady=8, sticky="w")

        self.btn_connect = ttk.Button(frame, text="连接串口", style="Primary.TButton", command=self.toggle_connection)
        self.btn_connect.grid(row=0, column=7, padx=10, pady=8, sticky="e")

    def scan_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.port_combo['values'] = port_list
        if port_list:
            self.port_combo.set(port_list[0])
            self.log(f"扫描完成，发现 {len(port_list)} 个可用端口")
        else:
            self.port_combo.set("")
            self.log("没有发现可用串口，请检查硬件连接")

    def _get_address(self):
        if not self.show_address:
            return 0
        return int(self.entry_address.get())

    def toggle_connection(self):
        if self.is_connected():
            if self.auto_var is not None:
                self.auto_var.set(False)
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
                self.controller = self.create_controller(port, int(baud), self._get_address())
                self.controller.open()
                self.btn_connect.config(text="断开连接", style="Success.TButton")
                self.update_btn_states(True)
            except Exception as e:
                self.controller = None
                messagebox.showerror(
                    "串口错误",
                    f"无法连接到该串口，可能被其他程序或本工具的其他选项卡占用。\n错误信息: {e}")
                self.log(f"连接失败: {e}")

    def is_connected(self):
        return (self.controller is not None
                and self.controller.serial is not None
                and self.controller.serial.is_open)

    def update_btn_states(self, connected):
        state = "normal" if connected else "disabled"
        for btn in self.op_buttons:
            btn.config(state=state)

    # ==================== 日志面板 ====================

    def _build_log_panel(self):
        frame = ttk.LabelFrame(self, text=" 报文日志 ")
        frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            frame, background="#1E1E1E", foreground="#D4D4D4", font=("Consolas", 10), height=8)
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

    # ==================== 后台线程操作 ====================

    def start_op(self, op_name, func, silent=False):
        """func 签名 fn(controller) -> result; result 非 None 时回调 render_result"""
        if not self.is_connected():
            return
        if self.busy:
            if not silent:
                self.log(f"上一操作尚未完成，忽略: {op_name}")
            return
        if self.show_address:
            try:
                self.controller.address = self._get_address()
            except ValueError:
                messagebox.showerror("参数错误", "地址必须为整数")
                return

        self.busy = True
        self.update_btn_states(False)
        # 在途操作期间禁止断开串口 (工作线程正持有 controller.serial)
        self.btn_connect.config(state="disabled")

        def worker():
            try:
                result = func(self.controller)
                self.after(0, lambda: self._on_op_success(op_name, result, silent))
            except Exception as e:
                # except 块退出时 e 会被解绑, lambda 延迟执行时不能再引用 e
                err_msg = str(e)
                self.after(0, lambda: self._on_op_error(op_name, err_msg, silent))

        threading.Thread(target=worker, daemon=True).start()

    def _on_op_success(self, op_name, result, silent):
        self.busy = False
        self.btn_connect.config(state="normal")
        if self.is_connected():
            self.update_btn_states(True)
        if not silent:
            self.log(f"{op_name} 完成")
        if result is not None:
            self.render_result(result)

    def _on_op_error(self, op_name, err_msg, silent):
        self.busy = False
        self.btn_connect.config(state="normal")
        if self.is_connected():
            self.update_btn_states(True)
        self.log(f"{op_name} 失败: {err_msg}")
        if not silent:
            messagebox.showerror("操作故障", f"{op_name} 失败: {err_msg}")

    # ==================== 自动刷新 ====================

    def build_auto_refresh(self, parent, row=0, column_start=0):
        """子类在自己的按钮区调用，放置自动刷新控件 (checkbox + 间隔 + '秒')"""
        self.auto_var = tk.BooleanVar(value=False)
        self._auto_after_id = None
        chk = ttk.Checkbutton(parent, text="自动刷新", variable=self.auto_var, command=self._on_auto_toggle)
        chk.grid(row=row, column=column_start, padx=(16, 4))
        self.combo_interval = ttk.Combobox(parent, values=["1", "2", "5", "10"], state="readonly", width=4)
        self.combo_interval.set("2")
        self.combo_interval.grid(row=row, column=column_start + 1, padx=2)
        ttk.Label(parent, text="秒").grid(row=row, column=column_start + 2, sticky="w")

    def _on_auto_toggle(self):
        if self.auto_var.get():
            self.log("自动刷新已开启")
            self._auto_tick()
        else:
            # 取消挂起的定时回调, 防止快速开/关/开产生并行刷新链
            if self._auto_after_id is not None:
                self.after_cancel(self._auto_after_id)
                self._auto_after_id = None
            self.log("自动刷新已关闭")

    def _auto_tick(self):
        if self.auto_var is None or not self.auto_var.get():
            self._auto_after_id = None
            return
        if self.is_connected() and not self.busy:
            self.on_auto_refresh()
        try:
            interval_ms = int(float(self.combo_interval.get()) * 1000)
        except ValueError:
            interval_ms = 2000
        self._auto_after_id = self.after(interval_ms, self._auto_tick)

    # ==================== 生命周期 ====================

    def close_page(self):
        """主窗口关闭时调用: 停自动刷新并关串口"""
        if self.auto_var is not None:
            self.auto_var.set(False)
        # 取消挂起的自动刷新定时回调 (未调用过 build_auto_refresh 的页面无此属性)
        if getattr(self, '_auto_after_id', None) is not None:
            self.after_cancel(self._auto_after_id)
            self._auto_after_id = None
        if self.is_connected():
            self.controller.close()
        self.controller = None
