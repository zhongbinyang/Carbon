#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk
from tkinter import ttk
from toolbox.base_page import setup_style
from toolbox.pages.iic_page import IicPage

# 测试环境无 mainloop, worker 线程改为同步执行 (与 test_base_page.py 相同处理)
import toolbox.base_page as _bp

class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
    def start(self):
        self._target()

_bp.threading.Thread = _SyncThread


class FakeIicController:
    """模拟 tbt_iic.TBTController: 读返回 12字节头+数据+状态+校验的响应帧"""
    def __init__(self):
        self.serial = self
        self.is_open = True
        self.calls = []

    def open(self): pass
    def close(self): self.is_open = False

    def send_and_receive(self, **kwargs):
        self.calls.append(('read', kwargs))
        data = bytes(range(0x41, 0x41 + 10))          # 'A'..'J'
        return bytes(12) + data + bytes([0x00, 0x99])  # 头12 + 数据10 + 状态 + 校验

    def write_page_iic(self, **kwargs):
        self.calls.append(('write', kwargs))
        return True


def pump(root, cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        root.update()
        time.sleep(0.01)


root = tk.Tk()
setup_style(root)
nb = ttk.Notebook(root)
nb.pack()
page = IicPage(nb)
nb.add(page, text="iic")
root.update()

# 默认值与原独立 GUI 一致
assert page.combo_port_type.get() == 'SFP'
assert page.entry_slave.get() == 'A0'
assert page.entry_size.get() == '10'
assert str(page.btn_read.cget('state')) == 'disabled'

# 注入 fake 控制器执行读取
page.controller = FakeIicController()
page.update_btn_states(True)
page.op_read()
pump(root, lambda: page.lbl_read_hex.cget('text') not in ('-', '读取中...'))

hex_text = page.lbl_read_hex.cget('text')
assert hex_text.startswith('41 42 43'), hex_text
assert 'ABCDEFGHIJ' in page.lbl_read_ascii.cget('text')
kind, kw = page.controller.calls[0]
assert kind == 'read'
assert kw['sub_cmd'] == 0 and kw['cmd_id'] == 2
assert kw['slave_addr'] == 0xA0 and kw['size'] == 10

# 写入路径
page.entry_write_data.delete(0, tk.END)
page.entry_write_data.insert(0, "11 22 33")
page.op_write()
pump(root, lambda: len(page.controller.calls) >= 2)
kind, kw = page.controller.calls[1]
assert kind == 'write'
assert kw['data'] == [0x11, 0x22, 0x33]
assert kw['slave_addr'] == 0xA0

root.destroy()
print("test_iic_page: OK")
