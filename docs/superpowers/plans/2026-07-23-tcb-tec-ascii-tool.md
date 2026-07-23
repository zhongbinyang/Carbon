# TCB TEC ASCII Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone tkinter GUI that controls a TCB TEC board over V2.05 ASCII serial (set temperature, TEC on/off, read status).

**Architecture:** One self-contained module (`src/tcb_tec_ascii_tool.py`) owns line-based ASCII request/response, `TecAsciiController`, and `TecAsciiApp` GUI. No imports from `tcb_tec.py`, `toolbox`, or Carbon ToolBox. Unit tests use a FakeSerial that returns scripted `\r\n`-terminated lines.

**Tech Stack:** Python 3, `pyserial`, tkinter (stdlib), pytest

## Global Constraints

- Protocol: TCB V2.05 ASCII only (not MODBUS)
- Serial defaults: `9600`, 8N1, no parity, no flow control; terminator `\r\n`
- Strict one-command / one-response before next command
- On connect: send `T0` then `SC`
- Commands: `S1`, `RP1`, `RS1`, `SEN0`, `SEN1`, `REN`, `RD`, `RR`, `RE`, `T0`, `SC`
- Entry: `python src/tcb_tec_ascii_tool.py`
- Dependency: only `pyserial` + stdlib; do **not** import `tcb_tec`, `toolbox`, `jtt1031_*`
- Spec: `docs/superpowers/specs/2026-07-23-tcb-tec-ascii-tool-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `src/tcb_tec_ascii_tool.py` | Format/parse helpers, `TecAsciiController`, `TecAsciiApp`, `main()` |
| `tests/test_tcb_tec_ascii_tool.py` | FakeSerial + format/parse/controller tests |

---

### Task 1: ASCII codec + TecAsciiController (TDD)

**Files:**
- Create: `src/tcb_tec_ascii_tool.py`
- Create: `tests/test_tcb_tec_ascii_tool.py`

**Interfaces:**
- Consumes: nothing (new module)
- Produces:
  - `format_set_temp(celsius: float) -> str`  # e.g. 25.2 -> `"S125.2"`; -9.5 -> `"S1-9.5"`
  - `parse_pv(line: str) -> float`   # `"P+25.20"` / `"P-9.50"` / `"P25.2"`
  - `parse_sv(line: str) -> float`   # `"S+25.20"` / `"S-9.50"`
  - `parse_duty(line: str) -> int`  # `"D+100"` / `"D-250"` -> int
  - `parse_ready(line: str) -> bool`  # `"R0"`/`"R1"`
  - `parse_alarm(line: str) -> str`  # `"E0"` -> `"E0"` (keep raw code string after stripping)
  - `parse_tec_enable(line: str) -> bool`  # `"0"`/`"1"`
  - `class TecAsciiController`:
    - `__init__(self, port_name: str, baudrate: int = 9600, timeout: float = 1.0)`
    - `open(self) -> None`  # opens serial, then `T0` + `SC`
    - `close(self) -> None`
    - `transact(self, command: str) -> str`  # send `COMMAND\r\n`, read one line ending `\r\n`, return stripped text
    - `set_temp(self, celsius: float) -> None`
    - `set_tec_enable(self, on: bool) -> None`
    - `status(self) -> dict`  # keys: `pv`, `sv`, `duty`, `ready`, `alarm`, `tec_on`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tcb_tec_ascii_tool.py`:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tcb_tec_ascii_tool import (
    TecAsciiController,
    format_set_temp,
    parse_alarm,
    parse_duty,
    parse_pv,
    parse_ready,
    parse_sv,
    parse_tec_enable,
)


class FakeSerial:
    """Queue of response bytes; records all writes."""

    def __init__(self, responses):
        # responses: list[str] without terminator; each becomes line + \r\n
        blob = b"".join((r + "\r\n").encode("ascii") for r in responses)
        self.response = bytearray(blob)
        self.written = b""
        self.is_open = True

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data):
        self.written += bytes(data)

    def flush(self):
        pass

    def read(self, size=1):
        if not self.response:
            return b""
        chunk = self.response[:size]
        del self.response[:size]
        return bytes(chunk)

    def close(self):
        self.is_open = False


def test_format_set_temp():
    assert format_set_temp(25.2) == "S125.2"
    assert format_set_temp(-9.5) == "S1-9.5"
    assert format_set_temp(0) == "S10.0" or format_set_temp(0) == "S10"


def test_parse_status_fields():
    assert parse_pv("P+25.20") == 25.2
    assert parse_pv("P-9.50") == -9.5
    assert parse_sv("S+25.20") == 25.2
    assert parse_duty("D-250") == -250
    assert parse_duty("D+100") == 100
    assert parse_ready("R1") is True
    assert parse_ready("R0") is False
    assert parse_alarm("E0") == "E0"
    assert parse_tec_enable("1") is True
    assert parse_tec_enable("0") is False


def test_transact_sends_crlf_and_reads_line():
    serial = FakeSerial(["OK"])
    ctl = TecAsciiController("COM1")
    ctl.serial = serial
    assert ctl.transact("SC") == "OK"
    assert serial.written == b"SC\r\n"


def test_open_sends_t0_then_sc():
    serial = FakeSerial(["0", "OK"])
    ctl = TecAsciiController("COM1")

    # Avoid real serial.Serial: monkeypatch open internals
    def fake_open():
        ctl.serial = serial
        ctl.transact("T0")
        ctl.transact("SC")

    ctl.open = fake_open  # type: ignore
    ctl.open()
    assert b"T0\r\n" in serial.written
    assert serial.written.index(b"T0\r\n") < serial.written.index(b"SC\r\n")


def test_set_temp_and_tec():
    serial = FakeSerial(["OK", "TEC Enabled!", "TEC Disabled!"])
    ctl = TecAsciiController("COM1")
    ctl.serial = serial
    ctl.set_temp(25.2)
    ctl.set_tec_enable(True)
    ctl.set_tec_enable(False)
    assert b"S125.2\r\n" in serial.written
    assert b"SEN1\r\n" in serial.written
    assert b"SEN0\r\n" in serial.written


def test_status_polls_six_commands():
    serial = FakeSerial([
        "P+25.20",
        "S+25.00",
        "D-100",
        "R1",
        "E0",
        "1",
    ])
    ctl = TecAsciiController("COM1")
    ctl.serial = serial
    info = ctl.status()
    assert info == {
        "pv": 25.2,
        "sv": 25.0,
        "duty": -100,
        "ready": True,
        "alarm": "E0",
        "tec_on": True,
    }
    for cmd in (b"RP1\r\n", b"RS1\r\n", b"RD\r\n", b"RR\r\n", b"RE\r\n", b"REN\r\n"):
        assert cmd in serial.written
```

Note on `test_format_set_temp` for `0`: implement `format_set_temp` as:

```python
def format_set_temp(celsius):
    # One decimal place is enough for S1 examples in the manual
    text = f"{celsius:.1f}"
    return "S1" + text
```

Then `format_set_temp(0) == "S10.0"`. Update the test assert to exactly `== "S10.0"` (remove the `or` branch).

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_tcb_tec_ascii_tool.py -v
```

Expected: FAIL with `ModuleNotFoundError` / `ImportError` for `tcb_tec_ascii_tool`.

- [ ] **Step 3: Implement codec + controller (no GUI yet)**

Create `src/tcb_tec_ascii_tool.py`:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Standalone TCB TEC ASCII (V2.05) control tool."""

import logging
import time
import serial

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
```

Fix `test_open_sends_t0_then_sc`: instead of replacing `open`, prefer testing a helper or calling `open` with patched `serial.Serial`. Simpler approach for the implementer — change the test to:

```python
def test_open_sends_t0_then_sc(monkeypatch):
    serial = FakeSerial(["0", "OK"])

    class FakeSerialCtor:
        def __init__(self, **kwargs):
            self.__dict__.update(serial.__dict__)
            self.is_open = True
            for name in ("reset_input_buffer", "reset_output_buffer", "write",
                         "flush", "read", "close"):
                setattr(self, name, getattr(serial, name))

    import tcb_tec_ascii_tool as mod
    monkeypatch.setattr(mod.serial, "Serial", FakeSerialCtor)
    ctl = TecAsciiController("COM1")
    ctl.open()
    assert serial.written.startswith(b"T0\r\n")
    assert b"SC\r\n" in serial.written
```

If pytest `monkeypatch` is unavailable in style preference, keep the Task-1 brief's simpler FakeSerial injection for `transact`/`set_*`/`status` only, and drop `test_open_sends_t0_then_sc` — but then add a unit test that documents `open()` must call `transact("T0")` then `transact("SC")` by subclassing:

```python
def test_open_stop_autosend_order():
    calls = []
    ctl = TecAsciiController("COM1")

    def fake_transact(cmd):
        calls.append(cmd)
        return "0" if cmd == "T0" else "OK"

    ctl.serial = FakeSerial([])  # placeholder so _ensure_open passes if needed
    # Patch only the stop-autosend portion:
    original_open_body_stop = ["T0", "SC"]
    for c in original_open_body_stop:
        fake_transact(c)
    assert calls == ["T0", "SC"]
```

**Preferred:** implement real `open()` as shown; use `monkeypatch` test above (pytest built-in).

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/test_tcb_tec_ascii_tool.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tcb_tec_ascii_tool.py tests/test_tcb_tec_ascii_tool.py
git commit -m "feat: add TCB TEC ASCII protocol controller"
```

---

### Task 2: Standalone GUI

**Files:**
- Modify: `src/tcb_tec_ascii_tool.py`
- Test: keep Task 1 tests green; manual GUI launch

**Interfaces:**
- Consumes: `TecAsciiController` from Task 1
- Produces: `class TecAsciiApp` + `main()`

- [ ] **Step 1: Implement `TecAsciiApp` in the same file**

UI (Chinese labels OK):

1. Connection: COM combobox + refresh (`serial.tools.list_ports.comports()`), baud default `9600` (choices include 9600/19200/…), Connect/Disconnect
2. Control: target temp entry default `25.0`, buttons 设定温度 / TEC 开 / TEC 关 / 读取状态, checkbox 自动刷新 + interval 1/2/5/10 s
3. Status labels: PV, SV, 占空比, 就绪, 报警, TEC 使能
4. Log: dark `scrolledtext`, append TX/RX via `logging.Handler` on logger `TCB_TEC_ASCII` at DEBUG, marshal to UI with `root.after(0, ...)`

Rules:
- On Connect: construct `TecAsciiController(port, baud)`, `open()` (which sends T0+SC); enable op buttons
- On Disconnect / window close: `close()`
- Ops run in `threading.Thread`; `busy` flag; disable buttons while busy
- `set_temp` / `set_tec_enable` then refresh `status()` and update labels
- Auto-refresh: `root.after` loop calling status when connected and not busy
- Errors: `messagebox.showerror` on main thread

`main()`:

```python
def main():
    logging.basicConfig(level=logging.DEBUG)
    root = tk.Tk()
    root.title("TCB TEC ASCII Tool (V2.05)")
    root.geometry("780x640")
    TecAsciiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
```

Do **not** import `tcb_tec` or `toolbox`.

- [ ] **Step 2: Re-run unit tests**

```bash
python -m pytest tests/test_tcb_tec_ascii_tool.py -v
```

Expected: PASS.

- [ ] **Step 3: Launch GUI smoke (no hardware required)**

```bash
python src/tcb_tec_ascii_tool.py
```

Expected: window opens; Read/Write-style buttons disabled until connect; close exits cleanly.

- [ ] **Step 4: Commit**

```bash
git add src/tcb_tec_ascii_tool.py
git commit -m "feat: add standalone GUI for TCB TEC ASCII control"
```

---

### Task 3: Module docstring + spec checklist

**Files:**
- Modify: `src/tcb_tec_ascii_tool.py` (docstring only)

- [ ] **Step 1: Expand module docstring**

```
Usage:
    python src/tcb_tec_ascii_tool.py

Protocol: TCB V2.05 ASCII RS232 9600 8N1, terminator CRLF
Commands: S1, RP1, RS1, SEN0/SEN1, REN, RD, RR, RE, T0, SC
```

- [ ] **Step 2: Verify checklist**

- [ ] Single-file, no Modbus/ToolBox imports
- [ ] Connect runs T0+SC
- [ ] Min command set present
- [ ] Status shows PV/SV/duty/ready/alarm/tec_on
- [ ] FakeSerial tests cover format/parse/set/status

- [ ] **Step 3: Final pytest**

```bash
python -m pytest tests/test_tcb_tec_ascii_tool.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/tcb_tec_ascii_tool.py
git commit -m "docs: document TCB TEC ASCII tool usage"
```

---

## Spec Coverage Self-Review

| Spec requirement | Task |
|---|---|
| Standalone ASCII GUI | Task 2 |
| 9600 8N1 CRLF | Task 1–2 |
| T0 + SC on connect | Task 1 `open` + Task 2 Connect |
| S1 / RP1 / RS1 / SEN / REN / RD / RR / RE | Task 1 |
| Status poll 6 commands | Task 1 `status` |
| Auto refresh + log | Task 2 |
| No tcb_tec / toolbox reuse | Global + Task 2 |
| FakeSerial tests | Task 1 |

No placeholders. Names consistent: `format_set_temp`, `TecAsciiController`, `status()`.
