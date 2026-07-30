#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from jtt1031_ber_tool import (
    CMD_CHECK_MODE,
    CMD_CLEAR,
    CMD_CONTROL,
    CMD_MODE,
    CMD_RATE,
    BerController,
    build_frame,
    checksum,
    parse_response,
    parse_status,
)


def _u32_list(values):
    return b"".join(value.to_bytes(4, "big") for value in values)


def _s32_list(values):
    return b"".join(value.to_bytes(4, "big", signed=True) for value in values)


def make_observed_payload(control=1, mode=4, rate=2, check=1):
    payload = bytearray([control, mode, rate, check])
    payload.extend([1, 0, 1, 0])
    payload.extend([1, 1, 0, 0])
    payload.extend((123).to_bytes(4, "big"))
    payload.extend(_u32_list([10, 20, 30, 40]))
    payload.extend(_u32_list([5, 0, 7, 0]))
    payload.extend(_u32_list([12, 0, 34, 0]))
    payload.extend(_s32_list([-12, 0, -11, 0]))
    assert len(payload) == 80
    return bytes(payload)


def make_documented_payload():
    payload = bytearray([1, 1, 4, 2])
    payload.extend([1, 0, 1, 0])
    payload.extend([1, 1, 0, 0])
    payload.append(1)
    payload.extend((123).to_bytes(4, "big"))
    payload.extend(_u32_list([10, 20, 30, 40]))
    payload.extend(_u32_list([5, 0, 7, 0]))
    payload.extend(_u32_list([12, 0, 34, 0]))
    payload.extend(_s32_list([-12, 0, -11, 0]))
    assert len(payload) == 81
    return bytes(payload)


def response_frame(address, command, payload):
    frame = bytearray([
        0x5A,
        address,
        0,
        0,
        (command >> 8) & 0xFF,
        command & 0xFF,
    ])
    frame.extend(payload)
    length = len(frame) + 1
    frame[2:4] = length.to_bytes(2, "big")
    frame.append(checksum(frame))
    return bytes(frame)


def test_builds_logged_3106_frame():
    assert build_frame(0, CMD_MODE, bytes([3, 4])) == bytes.fromhex(
        "A5 00 00 09 31 06 03 04 EC"
    )


def test_parse_response_validates_and_returns_payload():
    payload = make_observed_payload()
    frame = response_frame(0, CMD_RATE, payload)
    assert parse_response(frame, 0, CMD_RATE) == payload


def test_parses_observed_80_byte_status():
    status = parse_status(make_observed_payload())

    assert status.layout == "observed80"
    assert status.fec_on is None
    assert (status.control, status.tx_mode, status.tx_rate, status.check_mode) == (1, 4, 2, 1)
    assert status.runtime_s == 123
    assert status.ppg_lock == [1, 0, 1, 0]
    assert status.ed_lock == [1, 1, 0, 0]
    assert status.error_count == [5, 0, 7, 0]
    assert status.ber_strings() == ["12e-12", "0e0", "34e-11", "0e0"]


def test_parses_documented_81_byte_status():
    status = parse_status(make_documented_payload())

    assert status.layout == "documented81"
    assert status.fec_on is True
    assert (status.control, status.tx_mode, status.tx_rate, status.check_mode) == (1, 4, 2, 1)
    assert status.runtime_s == 123
    assert status.error_time == [10, 20, 30, 40]


def test_rejects_unknown_status_length():
    with pytest.raises(ValueError, match="79"):
        parse_status(bytes(79))


class RecordingController(BerController):
    def __init__(self, payload):
        super().__init__("COM1")
        self.payload = payload
        self.calls = []

    def transact(self, command, data=b""):
        self.calls.append((command, bytes(data)))
        return self.payload


def test_initialize_sends_commands_in_protocol_order():
    ctl = RecordingController(make_observed_payload())

    status = ctl.initialize(chn=3, mode=4, rate=2, check_mode=1, start=True)

    assert status.layout == "observed80"
    assert ctl.calls == [
        (CMD_MODE, bytes([3, 4])),
        (CMD_RATE, bytes([3, 2])),
        (CMD_CHECK_MODE, bytes([3, 1])),
        (CMD_CONTROL, bytes([3, 1])),
        (CMD_CLEAR, bytes([3])),
    ]


@pytest.mark.parametrize("chn", [-1, 256])
def test_query_rejects_channel_outside_one_byte(chn):
    ctl = RecordingController(make_observed_payload())
    with pytest.raises(ValueError, match="chn"):
        ctl.query_status(chn)
