#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
I2C 读写页 (迁移自原 tbt_iic_gui.py)
协议层复用 tbt_iic.TBTController; 读取走 send_and_receive + 页面侧宽容截取
(响应短于期望不报错、按实际长度截取, 与原 GUI 行为一致)。
"""

import tkinter as tk
from tkinter import ttk, messagebox

import tbt_iic
from toolbox.base_page import BasePage


def parse_hex_input(val_str):
    """十六进制优先解析 (兼容 0x 前缀与十进制), 与原 GUI 行为一致"""
    val_str = val_str.strip()
    if val_str.lower().startswith("0x"):
        return int(val_str, 16)
    try:
        return int(val_str, 16)
    except ValueError:
        return int(val_str)


class IicPage(BasePage):
    default_baud = "115200"
    show_address = False
    bridge_logger = tbt_iic.logger

    def build_body(self, parent):
        # 1. 设备参数配置
        param_frame = ttk.LabelFrame(parent, text=" I2C 设备配置 ")
        param_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        for i in range(4):
            param_frame.columnconfigure(i, weight=1)

        ttk.Label(param_frame, text="光模块类型:").grid(row=0, column=0, padx=5, pady=6, sticky="e")
        self.combo_port_type = ttk.Combobox(param_frame, values=["SFP", "XFP", "QSFP"], state="readonly", width=12)
        self.combo_port_type.set("SFP")
        self.combo_port_type.grid(row=0, column=1, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="器件物理地址 (Hex):").grid(row=0, column=2, padx=5, pady=6, sticky="e")
        self.entry_slave = ttk.Entry(param_frame, width=12)
        self.entry_slave.insert(0, "A0")
        self.entry_slave.grid(row=0, column=3, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="页选择 (Page):").grid(row=1, column=0, padx=5, pady=6, sticky="e")
        self.entry_page = ttk.Entry(param_frame, width=12)
        self.entry_page.insert(0, "0")
        self.entry_page.grid(row=1, column=1, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="起始地址 (Hex):").grid(row=1, column=2, padx=5, pady=6, sticky="e")
        self.entry_start = ttk.Entry(param_frame, width=12)
        self.entry_start.insert(0, "00")
        self.entry_start.grid(row=1, column=3, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="读写长度 (1-256):").grid(row=2, column=0, padx=5, pady=6, sticky="e")
        self.entry_size = ttk.Entry(param_frame, width=12)
        self.entry_size.insert(0, "10")
        self.entry_size.grid(row=2, column=1, padx=5, pady=6, sticky="w")

        ttk.Label(param_frame, text="槽位号 (Slot, 0-16):").grid(row=2, column=2, padx=5, pady=6, sticky="e")
        self.entry_slot = ttk.Entry(param_frame, width=12)
        self.entry_slot.insert(0, "0")
        self.entry_slot.grid(row=2, column=3, padx=5, pady=6, sticky="w")

        # 2. 读写操作区
        op_frame = ttk.LabelFrame(parent, text=" 操作与数据 ")
        op_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        op_frame.columnconfigure(1, weight=1)

        ttk.Label(op_frame, text="写入数据 (Hex, 逗号/空格分隔):").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.entry_write_data = ttk.Entry(op_frame)
        self.entry_write_data.insert(0, "11 22 33 44")
        self.entry_write_data.grid(row=0, column=1, columnspan=2, padx=5, pady=8, sticky="ew")

        btn_frame = ttk.Frame(op_frame)
        btn_frame.grid(row=1, column=0, columnspan=3, pady=8)

        self.btn_read = ttk.Button(btn_frame, text=" 读取数据 (Read) ", style="Primary.TButton", width=20, command=self.op_read)
        self.btn_read.grid(row=0, column=0, padx=15)
        self.op_buttons.append(self.btn_read)

        self.btn_write = ttk.Button(btn_frame, text=" 写入数据 (Write) ", style="Success.TButton", width=20, command=self.op_write)
        self.btn_write.grid(row=0, column=1, padx=15)
        self.op_buttons.append(self.btn_write)

        # 3. 读取结果显示
        result_frame = ttk.Frame(op_frame)
        result_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=2)
        ttk.Label(result_frame, text="[读取结果 - 十六进制]:", font=('Microsoft YaHei', 9, 'bold')).pack(side="left", padx=5)
        self.lbl_read_hex = ttk.Label(result_frame, text="-", font=('Consolas', 10, 'bold'), foreground='#0078D4')
        self.lbl_read_hex.pack(side="left", padx=5)
        ttk.Label(result_frame, text=" | [ASCII]:", font=('Microsoft YaHei', 9, 'bold')).pack(side="left", padx=5)
        self.lbl_read_ascii = ttk.Label(result_frame, text="-", font=('Consolas', 10, 'bold'), foreground='#107C41')
        self.lbl_read_ascii.pack(side="left", padx=5)

    def create_controller(self, port, baud, address):
        return tbt_iic.TBTController(port_name=port, baudrate=baud)

    # ==================== 操作 ====================

    def _read_params(self):
        return {
            'port_str': self.combo_port_type.get(),
            'slave_addr': parse_hex_input(self.entry_slave.get()),
            'start_addr': parse_hex_input(self.entry_start.get()),
            'page': parse_hex_input(self.entry_page.get()),
            'slot': int(self.entry_slot.get()),
            'length': int(self.entry_size.get()),
        }

    def op_read(self):
        try:
            p = self._read_params()
            if not 1 <= p['length'] <= 256:
                raise ValueError("读写长度必须在 1-256 之间")
        except ValueError as e:
            messagebox.showerror("参数错误", f"参数解析失败: {e}")
            return
        self.lbl_read_hex.config(text="读取中...")
        self.lbl_read_ascii.config(text="")
        port_id = tbt_iic.TBTController.PORT_TYPES[p['port_str']]

        def do(c):
            # 宽容截取: 不走严格校验的 read_iic(), 按实际报文长度取数据
            resp = c.send_and_receive(
                slot=p['slot'], board_type=0, sub_cmd=0, cmd_id=2,
                port_id=port_id, slave_addr=p['slave_addr'], page=p['page'],
                size=0 if p['length'] == 256 else p['length'],
                start_addr=p['start_addr'])
            data_end = max(12, len(resp) - 2)
            return ('read', bytes(resp[12:data_end])[:p['length']])

        self.start_op("I2C 读取", do)

    def op_write(self):
        try:
            p = self._read_params()
            raw = self.entry_write_data.get().replace(',', ' ').replace('0x', '').replace('0X', '')
            data_list = [int(x, 16) for x in raw.split()]
            if not data_list:
                raise ValueError("写入数据不能为空")
        except ValueError as e:
            messagebox.showerror("参数错误", f"参数解析失败: {e}")
            return

        def do(c):
            ok = c.write_page_iic(
                port_str=p['port_str'], slave_addr=p['slave_addr'],
                start_addr=p['start_addr'], data=data_list,
                slot=p['slot'], page=p['page'])
            if not ok:
                raise RuntimeError("写入失败，详见日志")
            return ('write', len(data_list))

        self.start_op("I2C 写入", do)

    # ==================== 渲染 ====================

    def render_result(self, result):
        kind, payload = result
        if kind == 'read':
            hex_str = payload.hex(' ').upper()
            ascii_str = payload.decode('ascii', errors='replace').replace('\n', ' ').replace('\r', '')
            self.lbl_read_hex.config(text=hex_str if hex_str else '(空)')
            self.lbl_read_ascii.config(text=ascii_str)
        elif kind == 'write':
            messagebox.showinfo("成功", f"I2C 页写入成功！({payload} 字节)")
