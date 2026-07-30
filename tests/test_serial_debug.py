#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from serial_debug import SerialDebugController, parse_hex_bytes


class FakeSerial:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.written = b""
        self.is_open = True
        self.in_waiting = len(self.incoming)

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data):
        self.written += bytes(data)
        return len(data)

    def flush(self):
        pass

    def read(self, size):
        chunk = self.incoming[:size]
        del self.incoming[:size]
        self.in_waiting = len(self.incoming)
        return bytes(chunk)

    def close(self):
        self.is_open = False


assert parse_hex_bytes("A5 01,00 0D") == bytes([0xA5, 0x01, 0x00, 0x0D])

ctl = SerialDebugController("COM1")
ctl.serial = FakeSerial(b"OK\r\n")

assert ctl.send_hex("A5 01") == bytes([0xA5, 0x01])
assert ctl.serial.written == bytes([0xA5, 0x01])

sent = ctl.send_text("T0", encoding="ascii", line_ending="CRLF")
assert sent == b"T0\r\n"
assert ctl.serial.written.endswith(b"T0\r\n")

assert ctl.read_available() == b"OK\r\n"
assert ctl.read_available() == b""

print("test_serial_debug: OK")
