#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
阶梯科技测试系统 BER (PRBS) 初始化与读取程序
依据《阶梯科技测试系统--底层通信协议JTT1031》4.21 节
(型号 0x1031/0x1030 -- TEC-100G BERT 子卡) 实现。

帧格式 (文档第二章，所有数据高字节在前):
    Byte 0   : 同步帧头 (PC下发 0xA5, 下位机上报 0x5A)
    Byte 1   : 业务板地址 (0-255)
    Byte 2-3 : 数据总长度 (含帧头到校验和的所有字节)
    Byte 4-5 : 命令字
    Byte 6~  : 数据
    Byte N   : 校验和 (前面所有字节之和取单字节)

BER 相关命令字:
    0x3101 PRBS状态查询    0x3102 PRBS测试控制(启/停)
    0x3103 PRBS检测模式    0x3104 PRBS误码清除
    0x3105 PRBS速率设置    0x3106 PRBS模式设置

依赖库:
    pip install pyserial

使用示例:
    1. 初始化 (PRBS31, 25.78G, 误码率检测) 并启动:
       python tbt_ber.py COM3 init --mode PRBS31 --rate 25.78G
    2. 读取 BER 状态:
       python tbt_ber.py COM3 status
    3. 清零误码 / 停止测试:
       python tbt_ber.py COM3 clear
       python tbt_ber.py COM3 stop

注意: 文档对 0x3101 回复数据区有两处未明确 (是否带前导端口字节、
误码率常数/指数的字段宽度)，解析器按剩余长度自适应，并在 DEBUG
日志输出原始报文，首次对接真机时请核对。
"""

import sys
import time
import argparse
import logging
from dataclasses import dataclass, field
from typing import List

import serial

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TBT_BER")

# PRBS 模式 (0x3106)
PRBS_MODES = {
    'PRBS7': 0,
    'PRBS9': 1,
    'PRBS15': 2,
    'PRBS23': 3,
    'PRBS31': 4,
}
PRBS_MODE_NAMES = {v: k for k, v in PRBS_MODES.items()}

# 速率 (0x3105)
RATES = {
    '25.78G': 1,
    '26.5625G': 2,
}
RATE_NAMES = {v: k for k, v in RATES.items()}

# 检测模式 (0x3103)
CHECK_MODES = {
    'RATIO': 1,   # 误码率检测
    'COUNT': 2,   # 误码数检测
}
CHECK_MODE_NAMES = {v: k for k, v in CHECK_MODES.items()}


@dataclass
class PrbsStatus:
    """0x3101 状态查询回复 (控制类命令 0x3102~0x3106 回复相同)"""
    running: bool                 # prbs-control: 1 start / 0 stop
    fec_on: bool                  # fec: 1 on / 0 off
    tx_mode: int                  # 0:PRBS7 1:PRBS9 2:PRBS15 3:PRBS23 4:PRBS31
    tx_rate: int                  # 1:25.78G 2:26.5625G
    ppg_lock: List[int]           # 发送端锁定状态[4]: 1 lock / 0 unlock
    ed_lock: List[int]            # 接收端锁定状态[4]: 1 lock / 0 unlock
    check_mode: int               # 1:误码率检测 2:误码数检测
    runtime_s: int                # prbs 运行时间
    error_time: List[int]         # 误码计时[4]
    error_count: List[int]        # 误码数[4]
    ber_mantissa: List[int]       # 误码率-常数[4]
    ber_exponent: List[int]       # 误码率-指数[4] (按有符号数解析)
    raw: bytes = field(repr=False, default=b'')

    def ber_strings(self):
        """按 常数 x 10^指数 组合出 4 通道误码率的可读表示"""
        return [f"{m}e{e}" for m, e in zip(self.ber_mantissa, self.ber_exponent)]

    def summary(self):
        lines = [
            f"运行状态 : {'运行中' if self.running else '停止'}"
            f"    FEC: {'开' if self.fec_on else '关'}",
            f"PRBS模式 : {PRBS_MODE_NAMES.get(self.tx_mode, self.tx_mode)}"
            f"    速率: {RATE_NAMES.get(self.tx_rate, self.tx_rate)}"
            f"    检测: {CHECK_MODE_NAMES.get(self.check_mode, self.check_mode)}",
            f"PPG锁定  : {self.ppg_lock}    ED锁定: {self.ed_lock}",
            f"运行时间 : {self.runtime_s} s",
            f"误码计时 : {self.error_time}",
            f"误码数   : {self.error_count}",
            f"误码率   : {self.ber_strings()}",
        ]
        return '\n'.join(lines)


def _be(data, offset, width):
    """大端解析无符号整数 (文档: 所有数据高字节在前)"""
    return int.from_bytes(data[offset:offset + width], 'big')


def _be_signed(data, offset, width):
    return int.from_bytes(data[offset:offset + width], 'big', signed=True)


class TBTBerController:
    def __init__(self, port_name, baudrate=115200, timeout=1.0, address=0):
        """
        :param port_name: 串口号 (如 'COM3')
        :param baudrate: 波特率，默认 115200 (与协议文档一致)
        :param timeout: 超时时间 (秒)
        :param address: 业务板地址 (0-255)
        """
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.address = address
        self.serial = None

    def open(self):
        try:
            self.serial = serial.Serial(
                port=self.port_name,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            logger.info(f"成功打开并配置串口: {self.port_name} (波特率: {self.baudrate})")
        except Exception as e:
            logger.error(f"打开串口 {self.port_name} 失败: {e}")
            raise

    def close(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info(f"串口 {self.port_name} 已成功关闭")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _calculate_checksum(self, frame_bytes):
        return sum(frame_bytes) & 0xFF

    def transact(self, command, data):
        """
        按协议帧格式组包发送，读取并校验响应，返回响应的数据区 (不含帧头和校验和)。
        :param command: 16位命令字 (如 0x3101)
        :param data: 数据区字节 (list 或 bytes)
        """
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("串口未打开，请先调用 open()")

        data = bytes(data)
        total_len = 7 + len(data)  # 帧头1 + 地址1 + 长度2 + 命令2 + 数据N + 校验1

        frame = bytes([
            0xA5,
            self.address & 0xFF,
            (total_len >> 8) & 0xFF,   # 长度高字节
            total_len & 0xFF,          # 长度低字节
            (command >> 8) & 0xFF,     # 命令字高字节
            command & 0xFF,            # 命令字低字节
        ]) + data
        frame += bytes([self._calculate_checksum(frame)])

        logger.debug(f"发送数据帧: {frame.hex(' ').upper()}")
        self.serial.reset_input_buffer()
        self.serial.write(frame)
        self.serial.flush()

        # 延时等待下位机处理 (与原 LabVIEW/tbt_iic 逻辑一致)
        time.sleep(0.1)

        # 读取响应头 4 字节，取出 16 位帧总长
        header = self.serial.read(4)
        if len(header) < 4:
            raise TimeoutError("读取响应帧头超时")
        if header[0] != 0x5A:
            raise ValueError(f"响应帧头错误: 预期 0x5A，实际 0x{header[0]:02X}")

        resp_len = (header[2] << 8) | header[3]
        if resp_len < 7:
            raise ValueError(f"响应帧长度非法: {resp_len}")

        remaining = self.serial.read(resp_len - 4)
        if len(remaining) < (resp_len - 4):
            raise TimeoutError("读取响应体超时")

        resp = header + remaining
        logger.debug(f"接收数据帧: {resp.hex(' ').upper()}")

        recv_checksum = resp[-1]
        calc_checksum = self._calculate_checksum(resp[:-1])
        if recv_checksum != calc_checksum:
            raise ValueError(f"响应校验和错误: 收到 0x{recv_checksum:02X}, 计算得到 0x{calc_checksum:02X}")

        resp_cmd = (resp[4] << 8) | resp[5]
        if resp_cmd != command:
            logger.warning(f"响应命令字 0x{resp_cmd:04X} 与请求 0x{command:04X} 不一致")

        return resp[6:-1]

    # ==================== 状态解析 ====================

    def _parse_status(self, data):
        """
        解析 0x3101 状态回复的数据区。

        字段布局 (依据文档 4.21):
            prbs-control(1) fec(1) tx-mode(1) tx-rate(1)
            ppglol[4] edlol[4] rx-check(1)
            rx-runtime(Long32) rx-errortime[4](Long32) rx-errorcount[4](Long32)
            rx-errorration-man[4] rx-erroration-exp[4]

        文档未写明误码率常数/指数的字段宽度 (仅标注 Int)，也未写明数据区
        是否带前导端口字节，这里按剩余长度自适应:
            固定部分 49 字节之后，剩余字节均分为 man[4] + exp[4]。
        """
        FIXED = 49  # 4 + 4 + 4 + 1 + 4 + 16 + 16

        offset = 0
        # 若带前导 chn/port 字节，剩余长度会多 1，(len-1-49) 可被 8 整除而 (len-49) 不可
        if len(data) >= FIXED + 8:
            if (len(data) - FIXED) % 8 != 0 and (len(data) - 1 - FIXED) % 8 == 0:
                logger.debug(f"检测到 1 字节前导端口字段: 0x{data[0]:02X}")
                offset = 1
        if len(data) - offset < FIXED + 8:
            raise ValueError(f"状态回复数据长度不足: {len(data)} 字节, 原始报文: {data.hex(' ').upper()}")

        width = (len(data) - offset - FIXED) // 8  # man/exp 单元素字节宽度

        p = offset
        running = data[p]; p += 1
        fec = data[p]; p += 1
        tx_mode = data[p]; p += 1
        tx_rate = data[p]; p += 1
        ppg = list(data[p:p + 4]); p += 4
        ed = list(data[p:p + 4]); p += 4
        check = data[p]; p += 1
        runtime = _be(data, p, 4); p += 4
        err_time = [_be(data, p + i * 4, 4) for i in range(4)]; p += 16
        err_cnt = [_be(data, p + i * 4, 4) for i in range(4)]; p += 16
        man = [_be(data, p + i * width, width) for i in range(4)]; p += 4 * width
        exp = [_be_signed(data, p + i * width, width) for i in range(4)]; p += 4 * width

        return PrbsStatus(
            running=bool(running), fec_on=bool(fec),
            tx_mode=tx_mode, tx_rate=tx_rate,
            ppg_lock=ppg, ed_lock=ed, check_mode=check,
            runtime_s=runtime, error_time=err_time, error_count=err_cnt,
            ber_mantissa=man, ber_exponent=exp, raw=bytes(data)
        )

    # ==================== BER 业务命令 ====================

    def query_status(self, chn=0):
        """0x3101 PRBS 状态查询"""
        data = self.transact(0x3101, [chn])
        return self._parse_status(data)

    def control(self, start, chn=0):
        """0x3102 PRBS 测试控制 (start=True 启动 / False 停止)"""
        data = self.transact(0x3102, [chn, 1 if start else 0])
        return self._parse_status(data)

    def set_check_mode(self, mode, chn=0):
        """0x3103 PRBS 检测模式 (1: 误码率检测, 2: 误码数检测)"""
        data = self.transact(0x3103, [chn, mode])
        return self._parse_status(data)

    def clear_errors(self, chn=0):
        """0x3104 PRBS 误码清除"""
        data = self.transact(0x3104, [chn])
        return self._parse_status(data)

    def set_rate(self, rate, chn=0):
        """0x3105 PRBS 速率设置 (1: 25.78G, 2: 26.5625G)"""
        data = self.transact(0x3105, [chn, rate])
        return self._parse_status(data)

    def set_prbs_mode(self, mode, chn=0):
        """0x3106 PRBS 模式设置 (0:PRBS7 1:PRBS9 2:PRBS15 3:PRBS23 4:PRBS31)"""
        data = self.transact(0x3106, [chn, mode])
        return self._parse_status(data)

    def init_ber(self, prbs_mode, rate, check_mode=1, chn=0, start=True):
        """
        BER 初始化流程: 设 PRBS 模式 -> 设速率 -> 设检测模式 -> (启动) -> 清零误码
        :return: 最后一步返回的 PrbsStatus
        """
        logger.info(f"BER 初始化: 通道 {chn}, 模式 {PRBS_MODE_NAMES.get(prbs_mode, prbs_mode)}, "
                    f"速率 {RATE_NAMES.get(rate, rate)}, 检测 {CHECK_MODE_NAMES.get(check_mode, check_mode)}")
        self.set_prbs_mode(prbs_mode, chn)
        self.set_rate(rate, chn)
        self.set_check_mode(check_mode, chn)
        if start:
            self.control(True, chn)
        status = self.clear_errors(chn)
        logger.info("BER 初始化完成")
        return status


def main():
    parser = argparse.ArgumentParser(description="TBT BER (PRBS) 初始化与读取命令行客户端")
    parser.add_argument("com", type=str, help="串口名称 (例如 COM3)")
    parser.add_argument("--address", type=int, default=0, help="业务板地址 (默认 0)")
    parser.add_argument("--chn", type=int, default=0, help="PRBS 测试通道 (默认 0)")
    parser.add_argument("--debug", action="store_true", help="输出收发报文 hex 日志")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化并启动 BER 测试")
    init_parser.add_argument("--mode", choices=list(PRBS_MODES), default="PRBS31", help="PRBS 模式 (默认 PRBS31)")
    init_parser.add_argument("--rate", choices=list(RATES), default="25.78G", help="速率 (默认 25.78G)")
    init_parser.add_argument("--check", choices=list(CHECK_MODES), default="RATIO",
                             help="检测模式: RATIO 误码率 / COUNT 误码数 (默认 RATIO)")
    init_parser.add_argument("--no-start", action="store_true", help="只配置参数，不启动测试")

    subparsers.add_parser("status", help="查询 BER 状态 (锁定/误码数/误码率)")
    subparsers.add_parser("start", help="启动 PRBS 测试")
    subparsers.add_parser("stop", help="停止 PRBS 测试")
    subparsers.add_parser("clear", help="清零误码计数")

    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        with TBTBerController(args.com, address=args.address) as ber:
            if args.command == "init":
                status = ber.init_ber(
                    prbs_mode=PRBS_MODES[args.mode],
                    rate=RATES[args.rate],
                    check_mode=CHECK_MODES[args.check],
                    chn=args.chn,
                    start=not args.no_start
                )
            elif args.command == "status":
                status = ber.query_status(args.chn)
            elif args.command == "start":
                status = ber.control(True, args.chn)
            elif args.command == "stop":
                status = ber.control(False, args.chn)
            elif args.command == "clear":
                status = ber.clear_errors(args.chn)

            print(f"\n[BER 状态]\n{status.summary()}")
    except Exception as e:
        logger.error(f"操作执行失败: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
