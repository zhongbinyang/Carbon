#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk
from tkinter import ttk
from toolbox.base_page import setup_style
from toolbox.pages.ber_page import BerPage
from tbt_ber import PrbsStatus

# 测试环境无 mainloop, worker 线程改为同步执行 (与 test_base_page.py 相同处理)
import toolbox.base_page as _bp

class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
    def start(self):
        self._target()

_bp.threading.Thread = _SyncThread

FAKE_STATUS = PrbsStatus(
    running=True, fec_on=False, tx_mode=4, tx_rate=1,
    ppg_lock=[1, 1, 1, 1], ed_lock=[1, 1, 0, 1], check_mode=1,
    runtime_s=3600, error_time=[10, 20, 30, 40], error_count=[5, 0, 7, 0],
    ber_mantissa=[12, 0, 34, 0], ber_exponent=[-12, 0, -11, 0])


class FakeBerController:
    def __init__(self):
        self.serial = self
        self.is_open = True
        self.calls = []
        self.address = 0

    def open(self): pass
    def close(self): self.is_open = False

    def query_status(self, chn=0):
        self.calls.append(('status', chn))
        return FAKE_STATUS

    def control(self, start, chn=0):
        self.calls.append(('control', start, chn))
        return FAKE_STATUS


def pump(root, cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        root.update()
        time.sleep(0.01)


root = tk.Tk()
setup_style(root)
nb = ttk.Notebook(root)
nb.pack()
page = BerPage(nb)
nb.add(page, text="ber")
root.update()

# 默认值与原独立 GUI 一致
assert page.combo_mode.get() == 'PRBS31'
assert page.combo_rate.get() == '25.78G'
assert page.combo_check.get() == 'RATIO'
assert page.entry_address.get() == '0'
assert str(page.btn_init.cget('state')) == 'disabled'

# 查询状态并渲染
page.controller = FakeBerController()
page.update_btn_states(True)
page.op_status()
pump(root, lambda: 'PRBS31' in page.lbl_summary.cget('text'))
assert '运行中' in page.lbl_summary.cget('text')
assert page.tree.item('2')['values'][2] == '失锁'
assert page.tree.item('0')['values'][5] == '12e-12'
assert page.controller.calls == [('status', 0)]
assert page.controller.address == 0

# 停止按钮走 control(False)
page.op_stop()
pump(root, lambda: len(page.controller.calls) >= 2)
assert page.controller.calls[1] == ('control', False, 0)

root.destroy()
print("test_ber_page: OK")
