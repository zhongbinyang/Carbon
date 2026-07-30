#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import tkinter as tk
from tkinter import ttk
from toolbox.base_page import BasePage, GuiLogHandler, setup_style

# tkinter 的 after() 在无 mainloop 的测试环境下不能从工作线程调用
# (RuntimeError: main thread is not in main loop)。测试中把 threading.Thread
# 换成同步桩, 让 start_op 的 worker 在主线程执行; 生产代码路径不变。
import toolbox.base_page as _bp

class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
    def start(self):
        self._target()

_bp.threading.Thread = _SyncThread


class FakeController:
    """满足 BasePage 对控制器的最小要求: open/close/serial"""
    def __init__(self):
        self.serial = self          # 让 controller.serial.is_open 可用
        self.is_open = True
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True
        self.is_open = False


class DummyPage(BasePage):
    default_baud = "9600"
    show_address = True
    address_label = "测试地址:"
    default_address = "7"

    def build_body(self, parent):
        self.results = []
        self.btn_test = ttk.Button(parent, text="op")
        self.btn_test.grid(row=0, column=0)
        self.op_buttons.append(self.btn_test)

    def create_controller(self, port, baud, address):
        return FakeController()

    def render_result(self, result):
        self.results.append(result)


def pump(root, cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        root.update()
        time.sleep(0.01)


root = tk.Tk()
setup_style(root)
nb = ttk.Notebook(root)
nb.pack()
page = DummyPage(nb)
nb.add(page, text="t")
root.update()

# 1. 初始状态: 按钮禁用、默认值生效
assert str(page.btn_test.cget('state')) == 'disabled'
assert page.baud_combo.get() == '9600'
assert page.entry_address.get() == '7'
assert page.is_connected() is False

# 2. 模拟连接后 start_op 成功路径 (含地址写回)
page.controller = FakeController()
page.update_btn_states(True)
assert str(page.btn_test.cget('state')) == 'normal'
page.start_op("测试操作", lambda c: 42)
pump(root, lambda: page.results)
assert page.results == [42]
assert page.busy is False
assert page.controller.address == 7

# 3. busy 防并发: busy 期间再发起被忽略
page.busy = True
page.start_op("并发操作", lambda c: 99, silent=True)
root.update()
assert page.results == [42]
page.busy = False

# 4. 异常路径 (silent): 不弹窗, busy 恢复
def boom(c):
    raise RuntimeError('boom')
page.start_op("失败操作", boom, silent=True)
pump(root, lambda: not page.busy)
assert page.busy is False
assert page.results == [42]

# 5. 日志面板
page.log("hello-log")
root.update()
assert "hello-log" in page.log_text.get("1.0", "end")

# 6. GuiLogHandler 转发
msgs = []
h = GuiLogHandler(msgs.append)
import logging
rec = logging.LogRecord("t", logging.DEBUG, "", 0, "bridged-msg", None, None)
h.emit(rec)
assert msgs == ["bridged-msg"]

# 7. close_page 关串口
ctl = page.controller
page.close_page()
assert ctl.closed is True
assert page.controller is None

# 8. 自动刷新: 快速 开->关->开->关 不产生并行定时链
class AutoPage(DummyPage):
    def build_body(self, parent):
        super().build_body(parent)
        self.build_auto_refresh(parent, row=1, column_start=0)
        self.refresh_calls = 0

    def on_auto_refresh(self):
        self.refresh_calls += 1

auto_page = AutoPage(nb)
nb.add(auto_page, text="a")
auto_page.controller = FakeController()
auto_page.update_btn_states(True)
auto_page.combo_interval.set("1")

# 开->关->开: 每次"开"立即 tick 一次 (refresh_calls +1), "关"应取消挂起回调
auto_page.auto_var.set(True); auto_page._on_auto_toggle()
auto_page.auto_var.set(False); auto_page._on_auto_toggle()
auto_page.auto_var.set(True); auto_page._on_auto_toggle()
assert auto_page.refresh_calls == 2
assert auto_page._auto_after_id is not None

# 等约 1.3 秒: 只应有一条链在跑, 即恰好再 +1 (若关闭未取消会 +2)
deadline = time.time() + 1.3
while time.time() < deadline:
    root.update()
    time.sleep(0.02)
assert auto_page.refresh_calls == 3, f"并行定时链: {auto_page.refresh_calls}"

# 关闭后不再增长
auto_page.auto_var.set(False); auto_page._on_auto_toggle()
assert auto_page._auto_after_id is None
deadline = time.time() + 1.2
while time.time() < deadline:
    root.update()
    time.sleep(0.02)
assert auto_page.refresh_calls == 3

root.destroy()
print("test_base_page: OK")
