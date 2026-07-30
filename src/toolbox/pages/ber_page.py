#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
BER (PRBS) 测试页 (迁移自原 tbt_ber_gui.py)
协议层复用 tbt_ber.TBTBerController (JTT1031 协议 0x3101~0x3106)。
"""

from tkinter import ttk, messagebox

import tbt_ber
from tbt_ber import (
    TBTBerController, PrbsStatus,
    PRBS_MODES, PRBS_MODE_NAMES, RATES, RATE_NAMES, CHECK_MODES, CHECK_MODE_NAMES,
)
from toolbox.base_page import BasePage


class BerPage(BasePage):
    default_baud = "115200"
    show_address = True
    address_label = "业务板地址:"
    default_address = "0"
    bridge_logger = tbt_ber.logger

    def build_body(self, parent):
        # 1. BER 参数配置
        param_frame = ttk.LabelFrame(parent, text=" BER 配置 (初始化下发) ")
        param_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for i in range(8):
            param_frame.columnconfigure(i, weight=1)

        ttk.Label(param_frame, text="PRBS 模式:").grid(row=0, column=0, padx=5, pady=6, sticky="e")
        self.combo_mode = ttk.Combobox(param_frame, values=list(PRBS_MODES), state="readonly", width=10)
        self.combo_mode.set("PRBS31")
        self.combo_mode.grid(row=0, column=1, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="速率:").grid(row=0, column=2, padx=5, pady=6, sticky="e")
        self.combo_rate = ttk.Combobox(param_frame, values=list(RATES), state="readonly", width=10)
        self.combo_rate.set("25.78G")
        self.combo_rate.grid(row=0, column=3, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="检测模式:").grid(row=0, column=4, padx=5, pady=6, sticky="e")
        self.combo_check = ttk.Combobox(param_frame, values=list(CHECK_MODES), state="readonly", width=10)
        self.combo_check.set("RATIO")
        self.combo_check.grid(row=0, column=5, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="通道 (chn):").grid(row=0, column=6, padx=5, pady=6, sticky="e")
        self.entry_chn = ttk.Entry(param_frame, width=6)
        self.entry_chn.insert(0, "0")
        self.entry_chn.grid(row=0, column=7, padx=5, pady=6, sticky="w")

        # 2. 操作按钮区
        op_frame = ttk.LabelFrame(parent, text=" 操作 ")
        op_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        op_frame.columnconfigure(0, weight=1)

        btn_frame = ttk.Frame(op_frame)
        btn_frame.grid(row=0, column=0, pady=8)

        self.btn_init = ttk.Button(btn_frame, text=" 初始化并启动 ", style="Success.TButton", width=16, command=self.op_init)
        self.btn_init.grid(row=0, column=0, padx=8)
        self.btn_status = ttk.Button(btn_frame, text=" 查询状态 ", style="Primary.TButton", width=12, command=self.op_status)
        self.btn_status.grid(row=0, column=1, padx=8)
        self.btn_start = ttk.Button(btn_frame, text=" 启动 ", width=8, command=self.op_start)
        self.btn_start.grid(row=0, column=2, padx=8)
        self.btn_stop = ttk.Button(btn_frame, text=" 停止 ", style="Danger.TButton", width=8, command=self.op_stop)
        self.btn_stop.grid(row=0, column=3, padx=8)
        self.btn_clear_err = ttk.Button(btn_frame, text=" 误码清零 ", width=10, command=self.op_clear)
        self.btn_clear_err.grid(row=0, column=4, padx=8)
        self.op_buttons.extend([self.btn_init, self.btn_status, self.btn_start, self.btn_stop, self.btn_clear_err])

        self.build_auto_refresh(btn_frame, row=0, column_start=5)

        # 3. 状态显示区
        status_frame = ttk.LabelFrame(parent, text=" BER 状态 ")
        status_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        status_frame.columnconfigure(0, weight=1)

        self.lbl_summary = ttk.Label(
            status_frame, text="运行状态: -    FEC: -    模式: -    速率: -    检测: -    运行时间: -",
            font=('Microsoft YaHei', 10, 'bold'), foreground='#0078D4')
        self.lbl_summary.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))

        columns = ("chn", "ppg", "ed", "errcnt", "errtime", "ber")
        self.tree = ttk.Treeview(status_frame, columns=columns, show="headings", height=4)
        headings = {"chn": "通道", "ppg": "PPG锁定", "ed": "ED锁定",
                    "errcnt": "误码数", "errtime": "误码计时", "ber": "误码率"}
        widths = {"chn": 60, "ppg": 90, "ed": 90, "errcnt": 140, "errtime": 140, "ber": 160}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")
        for i in range(4):
            self.tree.insert("", "end", iid=str(i), values=(f"CH{i}", "-", "-", "-", "-", "-"))
        self.tree.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 8))

    def create_controller(self, port, baud, address):
        return TBTBerController(port_name=port, baudrate=baud, address=address)

    # ==================== 操作 ====================

    def _get_chn(self):
        try:
            return int(self.entry_chn.get())
        except ValueError:
            messagebox.showerror("参数错误", "通道必须为整数")
            return None

    def op_init(self):
        chn = self._get_chn()
        if chn is None:
            return
        mode = PRBS_MODES[self.combo_mode.get()]
        rate = RATES[self.combo_rate.get()]
        check = CHECK_MODES[self.combo_check.get()]
        self.start_op("BER 初始化", lambda c: c.init_ber(
            prbs_mode=mode, rate=rate, check_mode=check, chn=chn, start=True))

    def op_status(self):
        chn = self._get_chn()
        if chn is not None:
            self.start_op("状态查询", lambda c: c.query_status(chn))

    def op_start(self):
        chn = self._get_chn()
        if chn is not None:
            self.start_op("启动 PRBS", lambda c: c.control(True, chn))

    def op_stop(self):
        chn = self._get_chn()
        if chn is not None:
            self.start_op("停止 PRBS", lambda c: c.control(False, chn))

    def op_clear(self):
        chn = self._get_chn()
        if chn is not None:
            self.start_op("误码清零", lambda c: c.clear_errors(chn))

    def on_auto_refresh(self):
        try:
            chn = int(self.entry_chn.get())
        except ValueError:
            return
        self.start_op("自动刷新", lambda c: c.query_status(chn), silent=True)

    # ==================== 渲染 ====================

    def render_result(self, status: PrbsStatus):
        summary = (f"运行状态: {'运行中' if status.running else '停止'}    "
                   f"FEC: {'开' if status.fec_on else '关'}    "
                   f"模式: {PRBS_MODE_NAMES.get(status.tx_mode, status.tx_mode)}    "
                   f"速率: {RATE_NAMES.get(status.tx_rate, status.tx_rate)}    "
                   f"检测: {CHECK_MODE_NAMES.get(status.check_mode, status.check_mode)}    "
                   f"运行时间: {status.runtime_s} s")
        self.lbl_summary.config(text=summary,
                                foreground='#107C41' if status.running else '#C42B1C')

        ber_strs = status.ber_strings()
        for i in range(4):
            self.tree.item(str(i), values=(
                f"CH{i}",
                "锁定" if status.ppg_lock[i] else "失锁",
                "锁定" if status.ed_lock[i] else "失锁",
                status.error_count[i],
                status.error_time[i],
                ber_strs[i],
            ))
