#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Standalone JTT1031 register-mode (0x0016/0x0017) serial test tool."""

import logging
import serial

logger = logging.getLogger("JTT1031_REG")

CMD_READ = 0x0016
CMD_WRITE = 0x0017


def checksum(data):
    return sum(data) & 0xFF


def build_frame(address, command, data=b""):
    data = bytes(data or b"")
    length = 7 + len(data)
    frame = bytearray([
        0xA5,
        address & 0xFF,
        (length >> 8) & 0xFF,
        length & 0xFF,
        (command >> 8) & 0xFF,
        command & 0xFF,
    ])
    frame.extend(data)
    frame.append(checksum(frame))
    return bytes(frame)


def parse_response(frame, expect_address, expect_command):
    if len(frame) < 7:
        raise ValueError("response too short")
    if frame[0] != 0x5A:
        raise ValueError(f"bad head: 0x{frame[0]:02X}")
    if frame[1] != (expect_address & 0xFF):
        raise ValueError("address mismatch")
    length = (frame[2] << 8) | frame[3]
    if length != len(frame):
        raise ValueError("length mismatch")
    if checksum(frame[:-1]) != frame[-1]:
        raise ValueError("checksum error")
    command = (frame[4] << 8) | frame[5]
    if command != expect_command:
        raise ValueError("command mismatch")
    return frame[6:-1]


class RegController:
    def __init__(self, port_name, baudrate=115200, timeout=1.0, address=0):
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.address = address
        self.serial = None

    def open(self):
        self.serial = serial.Serial(
            port=self.port_name,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    def _ensure_open(self):
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("serial not open")

    def _transact(self, command, data=b""):
        self._ensure_open()
        frame = build_frame(self.address, command, data)
        logger.debug("TX: %s", frame.hex(" ").upper())
        self.serial.reset_input_buffer()
        self.serial.write(frame)
        self.serial.flush()

        header = self.serial.read(4)
        if len(header) < 4:
            raise TimeoutError("timeout waiting response header")
        length = (header[2] << 8) | header[3]
        if length < 7:
            raise ValueError("response length too short")
        rest = self.serial.read(length - 4)
        if len(rest) < length - 4:
            raise TimeoutError("timeout waiting response body")
        response = header + rest
        logger.debug("RX: %s", response.hex(" ").upper())
        return parse_response(response, self.address, command)

    def read_register(self, port, dev_address, start_reg, size):
        if not 1 <= size <= 128:
            raise ValueError("size must be 1..128")
        payload = self._transact(CMD_READ, bytes([port, dev_address, start_reg, size]))
        if len(payload) < 5 + size:
            raise ValueError("0x0016 response too short")
        state, r_port, r_dev, r_start, r_size = payload[:5]
        if state != 1:
            raise ValueError(f"invalid state: {state}")
        if (r_port, r_dev, r_start, r_size) != (port, dev_address, start_reg, size):
            raise ValueError("0x0016 echo mismatch")
        return payload[5:5 + size]

    def write_register(self, port, dev_address, start_reg, data):
        data = bytes(data)
        if not 1 <= len(data) <= 128:
            raise ValueError("data length must be 1..128")
        payload = self._transact(
            CMD_WRITE,
            bytes([port, dev_address, start_reg, len(data)]) + data,
        )
        if len(payload) < 5:
            raise ValueError("0x0017 response too short")
        state, r_port, r_dev, r_start, r_size = payload[:5]
        if state != 1:
            raise ValueError(f"invalid state: {state}")
        if (r_port, r_dev, r_start, r_size) != (port, dev_address, start_reg, len(data)):
            raise ValueError("0x0017 echo mismatch")


if __name__ == "__main__":
    pass
