#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
TCB 系列温控板 温度设置/读取程序 (MODBUS RTU)
依据《AppNotes TCB 系列温控板 MODBUS 通信协议技术文档 V1.00》实现。

通信参数: MODBUS RTU, 默认 9600 波特率, 8N1 无校验, 从机地址默认 128 (0x80)。

切换 MODBUS 模式注意事项 (文档第八章):
    1. 温控板需先通过 ASCII 命令 `SMS1` 且 CTL 口 W 引脚接地才工作在 MODBUS 模式;
    2. 切入 MODBUS 前务必先发 ASCII 命令 `T0` 停止温控板自动上报, 否则总线数据碰撞;
    3. 帧与帧之间需保留至少 5ms 停顿间隔 (本程序已内置)。

勘误: 文档第七章示例帧尾的 CRC 值有误 (经穷举验证不存在能同时满足全部
示例的 CRC-16 参数)。本程序采用文档声明的标准 MODBUS CRC-16 (多项式
0xA001, 初值 0xFFFF, 低字节在前)，已对照公开标准向量验证。

寄存器映射 (AI/AO 数值均为 INT16S, 温度类放大 100 倍):
    输入寄存器 (功能码 04):
        0x0000 PV 当前温度 (x100)    0x0001 SV 设定温度 (x100)
        0x0002 TEC 占空比 (+-999)    0x0003 报警状态位
    保持寄存器 (功能码 03 读 / 06 写):
        0x0000 SV 设定温度 (x100)    0x0001 最大占空比 U (20-100)
        0x0002 PID 周期 T            0x0003 PID P    0x0004 PID I    0x0005 PID D
        0x0007 TEC 使能              0x000E Modbus 地址 (128-247)
    线圈 (功能码 05 写, 01 读):
        0x0000 TEC 开关 (ON=0xFF00, OFF=0x0000)
    离散输入 (功能码 02 读):
        0x0000 就绪状态              0x0001 运行状态

依赖库:
    pip install pyserial

使用示例:
    python tcb_tec.py COM4 read                # 读当前温度/设定温度/占空比
    python tcb_tec.py COM4 set 35.5            # 设定目标温度 35.5 度
    python tcb_tec.py COM4 tec on              # 打开 TEC 输出
    python tcb_tec.py COM4 status              # 读完整状态 (含报警位/就绪)
"""

import sys
import time
import argparse
import logging

import serial

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TCB_TEC")

# 报警状态位定义 (输入寄存器 0x0003, 依据 MODBUS 文档 6.2 节)
ALARM_BITS = {
    0: "温度报警(超限)",
    1: "长时间不就绪",
    2: "探头短路",
    3: "探头没接",
}


def crc16_modbus(data):
    """MODBUS CRC-16 (多项式 0xA001)，返回 2 字节: 低字节在前"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def to_int16s(value):
    """有符号 16 位转寄存器值 (文档: -950 -> 0xFC4A)"""
    if not -32768 <= value <= 32767:
        raise ValueError(f"数值超出 INT16S 范围: {value}")
    return value & 0xFFFF


def from_int16s(reg):
    """寄存器值转有符号 16 位"""
    return reg - 0x10000 if reg >= 0x8000 else reg


class TCBTecController:
    def __init__(self, port_name, baudrate=9600, timeout=1.0, address=128):
        """
        :param port_name: 串口号 (如 'COM4')
        :param baudrate: 波特率，默认 9600 (与出厂设置一致)
        :param timeout: 超时时间 (秒)
        :param address: MODBUS 从机地址 (128-247, 出厂默认 128; 0 为广播只写不回)
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
            logger.info(f"成功打开并配置串口: {self.port_name} (波特率: {self.baudrate}, 从机地址: {self.address})")
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

    # ==================== MODBUS RTU 收发 ====================

    def _transact(self, pdu):
        """
        发送 [地址][PDU][CRC16] 并读取校验响应，返回响应 PDU (不含地址和 CRC)。
        广播地址 0 时下位机不回复，返回 None。
        """
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("串口未打开，请先调用 open()")

        frame = bytes([self.address]) + bytes(pdu)
        frame += crc16_modbus(frame)

        # 帧与帧之间保留至少 5ms 停顿间隔 (文档第八章要求)
        time.sleep(0.005)

        logger.debug(f"发送数据帧: {frame.hex(' ').upper()}")
        self.serial.reset_input_buffer()
        self.serial.write(frame)
        self.serial.flush()

        if self.address == 0:
            return None

        # 读地址 + 功能码
        head = self.serial.read(2)
        if len(head) < 2:
            raise TimeoutError("等待温控板响应超时 (请检查从机地址和 MODBUS 模式是否开启)")
        if head[0] != self.address:
            raise ValueError(f"响应从机地址错误: 预期 {self.address}, 实际 {head[0]}")

        func = head[1]
        if func & 0x80:
            # MODBUS 异常响应: [地址][功能码|0x80][异常码][CRC]
            rest = self.serial.read(3)
            if len(rest) < 3:
                raise TimeoutError("读取异常响应超时")
            resp = head + rest
            self._check_crc(resp)
            raise ValueError(f"温控板返回 MODBUS 异常: 功能码 0x{func & 0x7F:02X}, 异常码 0x{rest[0]:02X}")

        if func in (0x01, 0x02, 0x03, 0x04):
            # [地址][功能码][字节数][数据...][CRC]
            count_byte = self.serial.read(1)
            if len(count_byte) < 1:
                raise TimeoutError("读取响应字节数超时")
            n = count_byte[0]
            rest = self.serial.read(n + 2)
            if len(rest) < n + 2:
                raise TimeoutError("读取响应数据超时")
            resp = head + count_byte + rest
        elif func in (0x05, 0x06):
            # 写响应为请求回显，固定 8 字节
            rest = self.serial.read(6)
            if len(rest) < 6:
                raise TimeoutError("读取写响应超时")
            resp = head + rest
        else:
            raise ValueError(f"不支持的响应功能码: 0x{func:02X}")

        logger.debug(f"接收数据帧: {resp.hex(' ').upper()}")
        self._check_crc(resp)
        return resp[1:-2]

    def _check_crc(self, frame):
        recv, calc = frame[-2:], crc16_modbus(frame[:-2])
        if recv != calc:
            raise ValueError(f"响应 CRC 校验错误: 收到 {recv.hex(' ').upper()}, 计算得到 {calc.hex(' ').upper()}")

    def _read_register(self, func, reg):
        """功能码 03/04 读单个寄存器，返回 INT16S 数值"""
        pdu = self._transact([func, reg >> 8, reg & 0xFF, 0x00, 0x01])
        # PDU: [功能码][字节数=2][数据高][数据低]
        if len(pdu) < 4 or pdu[1] != 2:
            raise ValueError(f"读寄存器响应格式错误: {pdu.hex(' ').upper()}")
        return from_int16s((pdu[2] << 8) | pdu[3])

    def _write_register(self, reg, value):
        """功能码 06 写单个寄存器 (响应为请求回显)"""
        raw = to_int16s(value)
        self._transact([0x06, reg >> 8, reg & 0xFF, (raw >> 8) & 0xFF, raw & 0xFF])

    def _write_coil(self, reg, on):
        """功能码 05 写线圈 (ON=0xFF00, OFF=0x0000)"""
        val = 0xFF00 if on else 0x0000
        self._transact([0x05, reg >> 8, reg & 0xFF, (val >> 8) & 0xFF, val & 0xFF])

    def _read_bit(self, func, reg):
        """功能码 01/02 读单个位"""
        pdu = self._transact([func, reg >> 8, reg & 0xFF, 0x00, 0x01])
        if len(pdu) < 3:
            raise ValueError(f"读位响应格式错误: {pdu.hex(' ').upper()}")
        return bool(pdu[2] & 0x01)

    # ==================== 温控业务接口 ====================

    def get_temp(self):
        """读当前温度 PV (摄氏度)"""
        value = self._read_register(0x04, 0x0000) / 100.0
        logger.info(f"当前温度 PV: {value:.2f} 度")
        return value

    def get_setpoint(self):
        """读设定温度 SV (摄氏度)"""
        value = self._read_register(0x04, 0x0001) / 100.0
        logger.info(f"设定温度 SV: {value:.2f} 度")
        return value

    def set_temp(self, celsius):
        """设定目标温度 SV (摄氏度, 精度 0.01)"""
        raw = round(celsius * 100)
        logger.info(f"设定目标温度: {celsius:.2f} 度 (寄存器值 {raw})")
        self._write_register(0x0000, raw)

    def get_duty(self):
        """读 TEC 当前占空比 (+-999, 负值代表制冷方向)"""
        return self._read_register(0x04, 0x0002)

    def get_alarms(self):
        """读报警状态，返回报警描述列表 (空列表代表正常)"""
        bits = self._read_register(0x04, 0x0003)
        return [name for bit, name in ALARM_BITS.items() if bits & (1 << bit)]

    def is_ready(self):
        """读就绪状态 (温度进入设定值 +-0.3 度且稳定)"""
        return self._read_bit(0x02, 0x0000)

    def set_tec_enable(self, on):
        """打开/关闭 TEC 输出"""
        logger.info(f"TEC 输出: {'打开' if on else '关闭'}")
        self._write_coil(0x0000, on)

    def get_pid(self):
        """读 PID 参数，返回 (T, P, I, D)"""
        return tuple(self._read_register(0x03, reg) for reg in (0x0002, 0x0003, 0x0004, 0x0005))

    def set_pid(self, p=None, i=None, d=None, t=None):
        """写 PID 参数 (只写指定的项)"""
        for reg, value in ((0x0002, t), (0x0003, p), (0x0004, i), (0x0005, d)):
            if value is not None:
                self._write_register(reg, value)

    def status(self):
        """读取完整状态，返回 dict"""
        info = {
            'pv': self.get_temp(),
            'sv': self.get_setpoint(),
            'duty': self.get_duty(),
            'alarms': self.get_alarms(),
            'ready': self.is_ready(),
        }
        return info


def main():
    parser = argparse.ArgumentParser(description="TCB 温控板 MODBUS 温度设置/读取命令行客户端")
    parser.add_argument("com", type=str, help="串口名称 (例如 COM4)")
    parser.add_argument("--addr", type=int, default=128, help="MODBUS 从机地址 (默认 128)")
    parser.add_argument("--baud", type=int, default=9600, help="波特率 (默认 9600)")
    parser.add_argument("--debug", action="store_true", help="输出收发报文 hex 日志")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("read", help="读当前温度/设定温度/占空比")

    set_parser = subparsers.add_parser("set", help="设定目标温度")
    set_parser.add_argument("temp", type=float, help="目标温度 (摄氏度, 如 35.5 或 -9.5)")

    tec_parser = subparsers.add_parser("tec", help="打开/关闭 TEC 输出")
    tec_parser.add_argument("switch", choices=["on", "off"])

    subparsers.add_parser("status", help="读完整状态 (含报警/就绪)")

    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        with TCBTecController(args.com, baudrate=args.baud, address=args.addr) as tec:
            if args.command == "read":
                pv = tec.get_temp()
                sv = tec.get_setpoint()
                duty = tec.get_duty()
                print(f"\n[温度读取]\n当前温度 PV: {pv:.2f} 度\n设定温度 SV: {sv:.2f} 度\nTEC 占空比 : {duty}")
            elif args.command == "set":
                tec.set_temp(args.temp)
                sv = tec.get_setpoint()
                print(f"\n[温度设定]\n设定完成，回读 SV: {sv:.2f} 度")
            elif args.command == "tec":
                tec.set_tec_enable(args.switch == "on")
                print(f"\n[TEC 控制]\nTEC 输出已{'打开' if args.switch == 'on' else '关闭'}")
            elif args.command == "status":
                info = tec.status()
                alarm_str = '、'.join(info['alarms']) if info['alarms'] else '正常'
                print(f"\n[温控板状态]\n当前温度 PV: {info['pv']:.2f} 度\n设定温度 SV: {info['sv']:.2f} 度\n"
                      f"TEC 占空比 : {info['duty']}\n就绪状态   : {'就绪' if info['ready'] else '未就绪'}\n"
                      f"报警状态   : {alarm_str}")
    except Exception as e:
        logger.error(f"操作执行失败: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
