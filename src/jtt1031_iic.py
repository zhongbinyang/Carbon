#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""JTT1031 direct protocol support for optical module IIC commands.

This module is separate from ``tbt_iic.py`` on purpose. The legacy module keeps
the LabVIEW-compatible bridge frame. This module implements the DOCX protocol:

    head, address, length(16-bit), command(16-bit), data..., checksum

All multi-byte fields are big-endian, and checksum is the low byte of the sum of
all previous frame bytes.
"""

import logging
import serial

logger = logging.getLogger("JTT1031_IIC")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class JTT1031IICController:
    CMD_READ_PAGE = 0x0012
    CMD_WRITE_PAGE = 0x0013
    CMD_READ_REGISTER = 0x0016
    CMD_WRITE_REGISTER = 0x0017

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
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        logger.info("Opened JTT1031 serial port %s at %s, address %s",
                    self.port_name, self.baudrate, self.address)

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def _calculate_checksum(frame_bytes):
        return sum(frame_bytes) & 0xFF

    @staticmethod
    def _u8(value, name):
        if not isinstance(value, int) or value < 0 or value > 0xFF:
            raise ValueError(f"{name} must be 0..255")
        return value

    @staticmethod
    def _bytes(values, name):
        try:
            data = bytes(values)
        except TypeError as exc:
            raise ValueError(f"{name} must be an iterable of bytes") from exc
        except ValueError as exc:
            raise ValueError(f"{name} contains a value outside 0..255") from exc
        return data

    def _ensure_open(self):
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("serial port is not open; call open() first")

    def build_frame(self, command, data=None):
        data = bytes(data or b"")
        self._u8(self.address, "address")
        if not isinstance(command, int) or command < 0 or command > 0xFFFF:
            raise ValueError("command must be 0..65535")

        length = 7 + len(data)
        if length > 0xFFFF:
            raise ValueError("frame is too long")

        frame = bytearray([
            0xA5,
            self.address & 0xFF,
            (length >> 8) & 0xFF,
            length & 0xFF,
            (command >> 8) & 0xFF,
            command & 0xFF,
        ])
        frame.extend(data)
        frame.append(self._calculate_checksum(frame))
        return bytes(frame)

    def transact(self, command, data=None):
        self._ensure_open()
        frame = self.build_frame(command, data)
        logger.debug("JTT1031 TX: %s", frame.hex(" ").upper())

        self.serial.reset_input_buffer()
        self.serial.write(frame)
        self.serial.flush()

        header = self.serial.read(4)
        if len(header) < 4:
            raise TimeoutError("timeout reading JTT1031 response header")
        if header[0] != 0x5A:
            raise ValueError(f"response header error: expected 0x5A, got 0x{header[0]:02X}")
        if header[1] != (self.address & 0xFF):
            raise ValueError(f"response address error: expected {self.address}, got {header[1]}")

        length = (header[2] << 8) | header[3]
        if length < 7:
            raise ValueError(f"response length too short: {length}")
        remaining = self.serial.read(length - 4)
        if len(remaining) < length - 4:
            raise TimeoutError("timeout reading JTT1031 response body")

        response = header + remaining
        logger.debug("JTT1031 RX: %s", response.hex(" ").upper())
        recv_checksum = response[-1]
        calc_checksum = self._calculate_checksum(response[:-1])
        if recv_checksum != calc_checksum:
            raise ValueError(
                f"response checksum error: got 0x{recv_checksum:02X}, calculated 0x{calc_checksum:02X}")

        response_command = (response[4] << 8) | response[5]
        if response_command != command:
            raise ValueError(f"response command error: expected 0x{command:04X}, got 0x{response_command:04X}")
        return response[6:-1]

    def read_module_page(self, port, part, page=0):
        """Command 0x0012: read one 128-byte A0/A2 page section."""
        self._u8(port, "port")
        self._u8(part, "part")
        self._u8(page, "page")
        if part not in (1, 2, 3, 4):
            raise ValueError("part must be 1(A0-L), 2(A0-H), 3(A2-L), or 4(A2-H)")

        payload = self.transact(self.CMD_READ_PAGE, [port, part, page])
        if len(payload) < 4 + 128:
            raise ValueError("0x0012 response is too short")
        state, resp_port, resp_part, resp_page = payload[:4]
        self._check_state(state)
        if (resp_port, resp_part, resp_page) != (port, part, page):
            raise ValueError("0x0012 response identity mismatch")
        return payload[4:4 + 128]

    def write_module_page(self, port, part, page, start_addr, data):
        """Command 0x0013: write optical module bytes by page."""
        data = self._bytes(data, "data")
        self._u8(port, "port")
        self._u8(part, "part")
        self._u8(page, "page")
        self._u8(start_addr, "start_addr")
        if part not in (1, 2, 3, 4):
            raise ValueError("part must be 1(A0-L), 2(A0-H), 3(A2-L), or 4(A2-H)")
        if not data or len(data) > 0xFF:
            raise ValueError("data length must be 1..255")

        payload = self.transact(self.CMD_WRITE_PAGE, [port, part, page, start_addr, len(data)] + list(data))
        if len(payload) < 6:
            raise ValueError("0x0013 response is too short")
        state, resp_port, resp_part, resp_page, resp_addr, resp_size = payload[:6]
        self._check_state(state)
        if (resp_port, resp_part, resp_page, resp_addr, resp_size) != (port, part, page, start_addr, len(data)):
            raise ValueError("0x0013 response identity mismatch")
        return True

    def read_register_iic(self, port, dev_address, start_reg, size):
        """Command 0x0016: read optical module bytes by device/register address."""
        self._u8(port, "port")
        self._u8(dev_address, "dev_address")
        self._u8(start_reg, "start_reg")
        self._u8(size, "size")
        if size < 1 or size > 128:
            raise ValueError("size must be 1..128")

        payload = self.transact(self.CMD_READ_REGISTER, [port, dev_address, start_reg, size])
        if len(payload) < 5 + size:
            raise ValueError("0x0016 response is too short")
        state, resp_port, resp_dev, resp_start, resp_size = payload[:5]
        self._check_state(state)
        if (resp_port, resp_dev, resp_start, resp_size) != (port, dev_address, start_reg, size):
            raise ValueError("0x0016 response identity mismatch")
        return payload[5:5 + size]

    def write_register_iic(self, port, dev_address, start_reg, data):
        """Command 0x0017: write optical module bytes by device/register address."""
        data = self._bytes(data, "data")
        self._u8(port, "port")
        self._u8(dev_address, "dev_address")
        self._u8(start_reg, "start_reg")
        if not data or len(data) > 128:
            raise ValueError("data length must be 1..128")

        payload = self.transact(self.CMD_WRITE_REGISTER, [port, dev_address, start_reg, len(data)] + list(data))
        if len(payload) < 5:
            raise ValueError("0x0017 response is too short")
        state, resp_port, resp_dev, resp_start, resp_size = payload[:5]
        self._check_state(state)
        if (resp_port, resp_dev, resp_start, resp_size) != (port, dev_address, start_reg, len(data)):
            raise ValueError("0x0017 response identity mismatch")
        return True

    @staticmethod
    def _check_state(state):
        if state != 1:
            raise ValueError(f"JTT1031 response state is invalid: {state}")
