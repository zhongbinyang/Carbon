#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
TEC 温控页 (迁移自原 tcb_tec_gui.py, MODBUS RTU)
协议层复用 tcb_tec.TCBTecController; 含 PV 温度实时曲线。
注意: 温控板需工作在 MODBUS 模式 (先经 ASCII 发送 T0 和 SMS1,
CTL 口 W 引脚接地), 详见 tcb_tec.py 模块说明。
"""

import time
import tkinter as tk
from tkinter import ttk, messagebox

import tcb_tec
from tcb_tec import TCBTecController
from toolbox.base_page import BasePage


class TempCurve:
    """PV 温度实时曲线 (Canvas 自绘): PV 实线 + 最新 SV 虚线参考线"""
    MAX_POINTS = 600

    def __init__(self, canvas):
        self.canvas = canvas
        self.points = []          # [(时间戳, pv, sv), ...]
        self.canvas.bind("<Configure>", lambda e: self.redraw())

    def add(self, pv, sv):
        self.points.append((time.time(), pv, sv))
        if len(self.points) > self.MAX_POINTS:
            self.points = self.points[-self.MAX_POINTS:]
        self.redraw()

    def clear(self):
        self.points = []
        self.redraw()

    def redraw(self):
        cv = self.canvas
        cv.delete("all")
        w = cv.winfo_width()
        h = cv.winfo_height()
        if w < 60 or h < 40:
            return

        margin_l, margin_r, margin_t, margin_b = 52, 10, 10, 22
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b

        cv.create_rectangle(margin_l, margin_t, w - margin_r, h - margin_b, outline="#555555")

        if len(self.points) < 2:
            cv.create_text(w / 2, h / 2, text="等待温度数据...", fill="#888888", font=("Microsoft YaHei", 10))
            return

        t0, t1 = self.points[0][0], self.points[-1][0]
        t_span = max(t1 - t0, 1e-6)

        values = [p[1] for p in self.points] + [self.points[-1][2]]
        v_min, v_max = min(values), max(values)
        pad = max((v_max - v_min) * 0.15, 0.2)
        v_min, v_max = v_min - pad, v_max + pad
        v_span = v_max - v_min

        def x_of(t):
            return margin_l + (t - t0) / t_span * plot_w

        def y_of(v):
            return margin_t + (v_max - v) / v_span * plot_h

        for i in range(5):
            v = v_min + v_span * i / 4
            y = y_of(v)
            cv.create_line(margin_l, y, w - margin_r, y, fill="#333333")
            cv.create_text(margin_l - 4, y, text=f"{v:.2f}", anchor="e", fill="#AAAAAA", font=("Consolas", 8))

        cv.create_text(margin_l, h - margin_b + 4, text="0s", anchor="n", fill="#AAAAAA", font=("Consolas", 8))
        cv.create_text(w - margin_r, h - margin_b + 4, text=f"{t_span:.0f}s", anchor="ne", fill="#AAAAAA", font=("Consolas", 8))

        sv = self.points[-1][2]
        if v_min <= sv <= v_max:
            y = y_of(sv)
            cv.create_line(margin_l, y, w - margin_r, y, fill="#C42B1C", dash=(5, 3))
            cv.create_text(w - margin_r - 4, y - 8, text=f"SV {sv:.2f}", anchor="e", fill="#C42B1C", font=("Consolas", 8))

        coords = []
        for t, pv, _ in self.points:
            coords.extend([x_of(t), y_of(pv)])
        cv.create_line(*coords, fill="#4EC9B0", width=2)


class TecPage(BasePage):
    default_baud = "9600"
    show_address = True
    address_label = "从机地址:"
    default_address = "128"
    bridge_logger = tcb_tec.logger

    def build_body(self, parent):
        parent.rowconfigure(2, weight=1)   # 曲线区可伸缩

        # 1. 温度控制
        ctrl_frame = ttk.LabelFrame(parent, text=" 温度控制 ")
        ctrl_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        ctrl_frame.columnconfigure(6, weight=1)

        ttk.Label(ctrl_frame, text="目标温度 (度):").grid(row=0, column=0, padx=(10, 5), pady=8, sticky="e")
        self.entry_temp = ttk.Entry(ctrl_frame, width=10)
        self.entry_temp.insert(0, "25.00")
        self.entry_temp.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        self.btn_set = ttk.Button(ctrl_frame, text=" 设定温度 ", style="Primary.TButton", width=12, command=self.op_set_temp)
        self.btn_set.grid(row=0, column=2, padx=10)
        self.btn_tec_on = ttk.Button(ctrl_frame, text=" TEC 开 ", style="Success.TButton", width=10, command=lambda: self.op_tec(True))
        self.btn_tec_on.grid(row=0, column=3, padx=8)
        self.btn_tec_off = ttk.Button(ctrl_frame, text=" TEC 关 ", style="Danger.TButton", width=10, command=lambda: self.op_tec(False))
        self.btn_tec_off.grid(row=0, column=4, padx=8)
        self.btn_status = ttk.Button(ctrl_frame, text=" 读取状态 ", width=10, command=self.op_status)
        self.btn_status.grid(row=0, column=5, padx=8)
        self.op_buttons.extend([self.btn_set, self.btn_tec_on, self.btn_tec_off, self.btn_status])

        self.build_auto_refresh(ctrl_frame, row=0, column_start=7)

        # 2. 状态显示
        status_frame = ttk.LabelFrame(parent, text=" 温控状态 ")
        status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        for i in range(5):
            status_frame.columnconfigure(i, weight=1)

        def status_pair(col, title):
            ttk.Label(status_frame, text=title, font=('Microsoft YaHei', 9)).grid(row=0, column=col, padx=5, pady=(6, 0))
            lbl = ttk.Label(status_frame, text="-", font=('Consolas', 16, 'bold'), foreground='#0078D4')
            lbl.grid(row=1, column=col, padx=5, pady=(0, 6))
            return lbl

        self.lbl_pv = status_pair(0, "当前温度 PV")
        self.lbl_sv = status_pair(1, "设定温度 SV")
        self.lbl_duty = status_pair(2, "TEC 占空比")
        self.lbl_ready = status_pair(3, "就绪状态")
        self.lbl_alarm = status_pair(4, "报警")

        # 3. PV 曲线
        curve_frame = ttk.LabelFrame(parent, text=" PV 温度曲线 ")
        curve_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        curve_frame.rowconfigure(0, weight=1)
        curve_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(curve_frame, background="#1E1E1E", highlightthickness=0, height=160)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.curve = TempCurve(self.canvas)

        btn_clear_curve = ttk.Button(curve_frame, text="清空曲线", command=self.curve.clear)
        btn_clear_curve.grid(row=1, column=0, sticky="e", padx=5, pady=(0, 5))

    def create_controller(self, port, baud, address):
        return TCBTecController(port_name=port, baudrate=baud, address=address)

    # ==================== 操作 ====================

    def op_set_temp(self):
        try:
            target = float(self.entry_temp.get())
        except ValueError:
            messagebox.showerror("参数错误", "目标温度必须为数字 (如 25.00 或 -9.5)")
            return

        def do(c):
            c.set_temp(target)
            return c.status()
        self.start_op(f"设定温度 {target:.2f} 度", do)

    def op_tec(self, on):
        def do(c):
            c.set_tec_enable(on)
            return c.status()
        self.start_op(f"TEC {'打开' if on else '关闭'}", do)

    def op_status(self):
        self.start_op("状态读取", lambda c: c.status())

    def on_auto_refresh(self):
        self.start_op("自动刷新", lambda c: c.status(), silent=True)

    # ==================== 渲染 ====================

    def render_result(self, info):
        self.lbl_pv.config(text=f"{info['pv']:.2f}")
        self.lbl_sv.config(text=f"{info['sv']:.2f}")
        self.lbl_duty.config(text=str(info['duty']))

        if info['ready']:
            self.lbl_ready.config(text="就绪", foreground='#107C41')
        else:
            self.lbl_ready.config(text="未就绪", foreground='#C42B1C')

        if info['alarms']:
            self.lbl_alarm.config(text='、'.join(info['alarms']), foreground='#C42B1C')
        else:
            self.lbl_alarm.config(text="正常", foreground='#107C41')

        self.curve.add(info['pv'], info['sv'])
