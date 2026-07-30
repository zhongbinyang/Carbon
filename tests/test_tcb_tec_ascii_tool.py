#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

import pytest

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
    assert format_set_temp(0) == "S10.0"


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


def test_transact_accepts_lf_only_line_ending():
    serial = FakeSerial([])
    serial.response = bytearray(b"OK\n")
    ctl = TecAsciiController("COM1")
    ctl.serial = serial
    assert ctl.transact("SC") == "OK"


def test_transact_skips_autosend_junk_until_expected():
    serial = FakeSerial(["P+25.20", "D-100", "OK"])
    ctl = TecAsciiController("COM1")
    ctl.serial = serial
    assert ctl.transact("SC", expect="OK") == "OK"
    assert serial.written == b"SC\r\n"


def test_open_sends_sc_then_t0(monkeypatch):
    # Vendor host software stops current auto-send with SC first, then T0.
    serial = FakeSerial(["OK", "0"])
    _patch_serial_ctor(monkeypatch, serial)
    ctl = TecAsciiController("COM1")
    ctl.open()
    assert serial.written.index(b"SC\r\n") < serial.written.index(b"T0\r\n")

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
    serial = FakeSerial(
        [
            "P+25.20",
            "S+25.00",
            "D-100",
            "R1",
            "E0",
            "1",
        ]
    )
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


def _patch_serial_ctor(monkeypatch, serial):
    class FakeSerialCtor:
        def __init__(self, **kwargs):
            self.__dict__.update(serial.__dict__)
            self.is_open = True
            for name in (
                "reset_input_buffer",
                "reset_output_buffer",
                "write",
                "flush",
                "read",
                "close",
            ):
                setattr(self, name, getattr(serial, name))

    import tcb_tec_ascii_tool as mod

    monkeypatch.setattr(mod.serial, "Serial", FakeSerialCtor)
    return mod


def test_open_closes_port_when_sc_never_ok(monkeypatch):
    serial = FakeSerial(["P+25.20", "D-1", "E0"])
    _patch_serial_ctor(monkeypatch, serial)
    ctl = TecAsciiController("COM1", timeout=0.2, handshake_timeout=0.2)
    with pytest.raises(TimeoutError, match="SC"):
        ctl.open()
    assert serial.is_open is False


def test_open_closes_port_when_t0_never_zero(monkeypatch):
    serial = FakeSerial(["OK", "P+25.20", "E0"])
    _patch_serial_ctor(monkeypatch, serial)
    ctl = TecAsciiController("COM1", timeout=0.2, handshake_timeout=0.2)
    with pytest.raises(TimeoutError, match="T0"):
        ctl.open()
    assert serial.is_open is False
