#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from jtt1031_iic import JTT1031IICController


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


def checksum(data):
    return sum(data) & 0xFF


def response_frame(address, command, payload):
    length = 7 + len(payload)
    frame = bytearray([0x5A, address, (length >> 8) & 0xFF, length & 0xFF,
                       (command >> 8) & 0xFF, command & 0xFF])
    frame.extend(payload)
    frame.append(checksum(frame))
    return bytes(frame)


def test_builds_docx_register_read_frame_and_returns_payload():
    payload = bytes([1, 3, 0xA0, 0x10, 4, 0x11, 0x22, 0x33, 0x44])
    serial = FakeSerial(response_frame(0x02, 0x0016, payload))
    ctl = JTT1031IICController("COM1", address=0x02)
    ctl.serial = serial

    data = ctl.read_register_iic(port=3, dev_address=0xA0, start_reg=0x10, size=4)

    assert data == bytes([0x11, 0x22, 0x33, 0x44])
    assert serial.written == bytes([0xA5, 0x02, 0x00, 0x0B, 0x00, 0x16,
                                    0x03, 0xA0, 0x10, 0x04, 0x7F])


def test_page_read_uses_0012_and_returns_128_bytes():
    read_data = bytes(range(128))
    payload = bytes([1, 5, 2, 7]) + read_data
    serial = FakeSerial(response_frame(0x01, 0x0012, payload))
    ctl = JTT1031IICController("COM1", address=0x01)
    ctl.serial = serial

    data = ctl.read_module_page(port=5, part=2, page=7)

    assert data == read_data
    assert serial.written[:6] == bytes([0xA5, 0x01, 0x00, 0x0A, 0x00, 0x12])
    assert serial.written[6:9] == bytes([5, 2, 7])
    assert serial.written[-1] == checksum(serial.written[:-1])


def test_write_register_iic_uses_0017_and_checks_response_identity():
    serial = FakeSerial(response_frame(0, 0x0017, bytes([1, 2, 0xA2, 0x20, 3])))
    ctl = JTT1031IICController("COM1")
    ctl.serial = serial

    assert ctl.write_register_iic(port=2, dev_address=0xA2, start_reg=0x20,
                                  data=[0xAA, 0xBB, 0xCC]) is True
    assert serial.written == bytes([0xA5, 0x00, 0x00, 0x0E, 0x00, 0x17,
                                    0x02, 0xA2, 0x20, 0x03,
                                    0xAA, 0xBB, 0xCC, 0xC2])


def test_invalid_state_raises_clear_error():
    serial = FakeSerial(response_frame(0, 0x0017, bytes([0, 2, 0xA2, 0x20, 3])))
    ctl = JTT1031IICController("COM1")
    ctl.serial = serial

    try:
        ctl.write_register_iic(port=2, dev_address=0xA2, start_reg=0x20, data=[1, 2, 3])
    except ValueError as exc:
        assert "state" in str(exc)
    else:
        raise AssertionError("expected invalid state to raise")


print("test_tbt_iic_jtt1031: OK")
