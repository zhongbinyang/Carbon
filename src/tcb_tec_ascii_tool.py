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
