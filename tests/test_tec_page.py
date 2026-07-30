#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk
from tkinter import ttk
from toolbox.base_page import setup_style
from toolbox.pages.tec_page import TecPage

# 测试环境无 mainloop, worker 线程改为同步执行 (与 test_base_page.py 相同处理)
import toolbox.base_page as _bp

class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
    def start(self):
        self._target()

_bp.threading.Thread = _SyncThread

FAKE_INFO = {'pv': 25.5, 'sv': 25.0, 'duty': -120, 'alarms': [], 'ready': True}


class FakeTecController:
    def __init__(self):
        self.serial = self
        self.is_open = True
        self.calls = []
        self.address = 128

    def open(self): pass
    def close(self): self.is_open = False

    def set_temp(self, celsius):
        self.calls.append(('set_temp', celsius))

    def set_tec_enable(self, on):
        self.calls.append(('tec', on))

    def status(self):
        self.calls.append(('status',))
        return dict(FAKE_INFO)


def pump(root, cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        root.update()
        time.sleep(0.01)


root = tk.Tk()
setup_style(root)
nb = ttk.Notebook(root)
nb.pack()
page = TecPage(nb)
nb.add(page, text="tec")
root.update()

# 默认值与原独立 GUI 一致
assert page.baud_combo.get() == '9600'
assert page.entry_address.get() == '128'
assert page.entry_temp.get() == '25.00'
assert str(page.btn_set.cget('state')) == 'disabled'

# 设温流程: set_temp + status 回读渲染
page.controller = FakeTecController()
page.update_btn_states(True)
page.entry_temp.delete(0, tk.END)
page.entry_temp.insert(0, "30.5")
page.op_set_temp()
pump(root, lambda: page.lbl_pv.cget('text') != '-')
assert page.controller.calls[0] == ('set_temp', 30.5)
assert page.lbl_pv.cget('text') == '25.50'
assert page.lbl_ready.cget('text') == '就绪'
assert page.lbl_alarm.cget('text') == '正常'
assert len(page.curve.points) == 1

# 报警渲染
page.render_result({'pv': 25.0, 'sv': 25.0, 'duty': 0,
                    'alarms': ['探头没接'], 'ready': False})
root.update()
assert '探头没接' in page.lbl_alarm.cget('text')
assert page.lbl_ready.cget('text') == '未就绪'

# 曲线清空
page.curve.clear()
assert page.curve.points == []

root.destroy()
print("test_tec_page: OK")
