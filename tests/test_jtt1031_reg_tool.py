#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from jtt1031_reg_tool import (
    CMD_READ,
    CMD_WRITE,
    RegController,
    build_frame,
    checksum,
    parse_response,
)


class FakeSerial:
    def __init__(self, response):
        self.response = bytearray(response)
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

    def read(self, size):
        chunk = self.response[:size]
        del self.response[:size]
        return bytes(chunk)

    def close(self):
        self.is_open = False


def response_frame(address, command, payload):
    body = bytearray([
        0x5A,
        address & 0xFF,
        0,
        0,
        (command >> 8) & 0xFF,
        command & 0xFF,
    ])
    body.extend(payload)
    length = len(body) + 1
    body[2] = (length >> 8) & 0xFF
    body[3] = length & 0xFF
    body.append(checksum(body))
    return bytes(body)


def test_checksum_is_low_byte_of_sum():
    assert checksum(bytes([0xA5, 0x00, 0x00, 0x0B, 0x00, 0x16])) == 0xC6


def test_build_frame_read_command():
    frame = build_frame(0x02, CMD_READ, bytes([0x03, 0xA0, 0x10, 0x04]))
    assert frame == bytes([0xA5, 0x02, 0x00, 0x0B, 0x00, 0x16, 0x03, 0xA0, 0x10, 0x04, 0x7F])


def test_parse_response_returns_payload():
    payload = bytes([1, 3, 0xA0, 0x10, 4, 0x11, 0x22, 0x33, 0x44])
    frame = response_frame(0x02, CMD_READ, payload)
    assert parse_response(frame, 0x02, CMD_READ) == payload


def test_read_register_returns_data():
    payload = bytes([1, 3, 0xA0, 0x10, 4, 0x11, 0x22, 0x33, 0x44])
    serial = FakeSerial(response_frame(0x02, CMD_READ, payload))
    ctl = RegController("COM1", address=0x02)
    ctl.serial = serial
    data = ctl.read_register(port=3, dev_address=0xA0, start_reg=0x10, size=4)
    assert data == bytes([0x11, 0x22, 0x33, 0x44])
    assert serial.written == build_frame(0x02, CMD_READ, bytes([3, 0xA0, 0x10, 4]))


def test_write_register_checks_echo():
    serial = FakeSerial(response_frame(0, CMD_WRITE, bytes([1, 2, 0xA2, 0x20, 3])))
    ctl = RegController("COM1", address=0)
    ctl.serial = serial
    ctl.write_register(port=2, dev_address=0xA2, start_reg=0x20, data=bytes([0xAA, 0xBB, 0xCC]))
    assert serial.written == build_frame(0, CMD_WRITE, bytes([2, 0xA2, 0x20, 3, 0xAA, 0xBB, 0xCC]))


def test_invalid_state_raises():
    serial = FakeSerial(response_frame(0, CMD_WRITE, bytes([0, 2, 0xA2, 0x20, 3])))
    ctl = RegController("COM1")
    ctl.serial = serial
    try:
        ctl.write_register(port=2, dev_address=0xA2, start_reg=0x20, data=bytes([1, 2, 3]))
    except ValueError as exc:
        assert "state" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
