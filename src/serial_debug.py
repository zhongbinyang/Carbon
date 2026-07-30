#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Generic serial port debug helpers."""

import logging
import re
import serial

logger = logging.getLogger("SERIAL_DEBUG")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


LINE_ENDINGS = {
    "": "",
    "None": "",
    "CR": "\r",
    "LF": "\n",
    "CRLF": "\r\n",
}


def parse_hex_bytes(text):
    """Parse hex text like 'A5 01,00' into bytes."""
    cleaned = text.replace(",", " ").replace(";", " ").replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"0x", "", cleaned, flags=re.IGNORECASE)
    parts = [part for part in cleaned.split() if part]
    if not parts:
        return b""
    values = []
    for part in parts:
        if len(part) > 2:
            if len(part) % 2 != 0:
                raise ValueError(f"invalid hex token: {part}")
            values.extend(int(part[i:i + 2], 16) for i in range(0, len(part), 2))
        else:
            values.append(int(part, 16))
    return bytes(values)


class SerialDebugController:
    def __init__(self, port_name, baudrate=115200, timeout=0.2):
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
        logger.info("Opened serial debug port %s at %s", self.port_name, self.baudrate)

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_open(self):
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("serial port is not open")

    def send_bytes(self, data):
        self._ensure_open()
        data = bytes(data)
        if not data:
            raise ValueError("send data cannot be empty")
        self.serial.write(data)
        self.serial.flush()
        logger.debug("TX: %s", data.hex(" ").upper())
        return data

    def send_hex(self, text):
        return self.send_bytes(parse_hex_bytes(text))

    def send_text(self, text, encoding="utf-8", line_ending=""):
        suffix = LINE_ENDINGS.get(line_ending, line_ending)
        return self.send_bytes((text + suffix).encode(encoding))

    def read_available(self, max_bytes=4096):
        self._ensure_open()
        waiting = getattr(self.serial, "in_waiting", 0)
        size = min(max(waiting, 1), max_bytes)
        data = self.serial.read(size)
        logger.debug("RX: %s", data.hex(" ").upper())
        return data
