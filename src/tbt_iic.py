#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
特比通 (TBT) I2C 读写串口通信控制程序
用于替代原有的 LabVIEW (writePageIIC.vi / readIIC.vi) 及其底层串口协议。

依赖库:
    pip install pyserial

使用示例:
    1. 命令行读取 SFP 模块 A0 地址偏移 0 处的 10 个字节:
       python tbt_iic.py COM3 read SFP 0xA0 0 10

    2. 命令行向 SFP 模块 A0 地址偏移 10 写入两个字节 0x11 和 0x22:
       python tbt_iic.py COM3 write SFP 0xA0 10 11,22
"""

import sys
import time
import argparse
import logging
import serial

# 设置日志格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TBT_IIC")

class TBTController:
    # 端口类型枚举
    PORT_TYPES = {
        'SFP': 1,
        'XFP': 2,
        'QSFP': 3
    }

    def __init__(self, port_name, baudrate=115200, timeout=1.0):
        """
        初始化 TBT 串口控制器
        :param port_name: 串口号 (如 'COM3' 或 '/dev/ttyUSB0')
        :param baudrate: 波特率，默认 115200 (与 LabVIEW 保持一致)
        :param timeout: 超时时间 (秒)
        """
        self.port_name = port_name
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None

    def open(self):
        """
        打开并配置串口
        """
        try:
            # 与 LabVIEW 配置一致: 115200, 8N1, 无流控, 不使用终止符
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
        """
        关闭串口会话
        """
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info(f"串口 {self.port_name} 已成功关闭")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _calculate_checksum(self, frame_bytes):
        """
        计算帧的累加和校验码 (Checksum)
        :param frame_bytes: 字节数组
        :return: 1字节校验和 (0-255)
        """
        return sum(frame_bytes) & 0xFF

    def send_and_receive(self, slot, board_type, sub_cmd, cmd_id, port_id, slave_addr, page, size, start_addr, payload=None):
        """
        按照特比通协议打包并发送指令，然后读取并解析下位机的响应。
        
        请求帧格式 (A5 开头):
            Byte 0: 帧头 0xA5
            Byte 1: 槽位号 (1-10，背板固定为 16，即 0x10；单板测试默认为 0)
            Byte 2: 业务选择/板卡类别 (公共命令为 0)
            Byte 3: 帧总长度 (12 + payload 长度)
            Byte 4: 子命令索引 (0: 读, 1: 写)
            Byte 5: 命令ID (2: 读, 3: 写)
            Byte 6: 端口类型 (1: SFP, 2: XFP, 3: QSFP)
            Byte 7: 器件物理地址 (如 0xA0)
            Byte 8: 寄存器页选择 (Page, 默认为 0)
            Byte 9: 读写大小 (SIZE, 0 代表 256 字节，其它为实际长度)
            Byte 10: 寄存器起始地址
            Byte 11..N: 数据负载 (仅写操作包含)
            Byte N+1: 校验和
        """
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("串口未打开，请先调用 open()")

        # 1. 组包请求帧
        payload_len = len(payload) if payload else 0
        total_len = 12 + payload_len

        # 构建头部 (前11字节，长度占位设为0，后续填入)
        frame = [
            0xA5,         # Header
            slot,         # Slot
            board_type,   # Board Type
            total_len,    # Length (Byte 3)
            sub_cmd,      # Sub-command
            cmd_id,       # Command ID
            port_id,      # Port Type (SFP=1, XFP=2, QSFP=3)
            slave_addr,   # Slave Addr
            page,         # Page
            size,         # Size
            start_addr    # Start Addr
        ]

        if payload:
            frame.extend(payload)

        # 计算并追加校验和
        checksum = self._calculate_checksum(frame)
        frame.append(checksum)

        # 2. 发送帧
        frame_bytes = bytes(frame)
        logger.debug(f"发送数据帧: {frame_bytes.hex(' ').upper()}")
        
        # 清空缓冲区防止干扰
        self.serial.reset_input_buffer()
        self.serial.write(frame_bytes)
        self.serial.flush()

        # 延时等待下位机处理 (根据 LabVIEW 延时逻辑)
        time.sleep(0.1)

        # 3. 读取响应帧
        # 首先读取响应头的前 4 个字节，以获取实际帧长度 (Byte 3)
        header_bytes = self.serial.read(4)
        if len(header_bytes) < 4:
            raise TimeoutError("读取响应帧头超时")

        if header_bytes[0] != 0x5A:
            raise ValueError(f"响应帧头错误: 预期 0x5A，实际 0x{header_bytes[0]:02X}")

        resp_len = header_bytes[3]
        logger.debug(f"响应帧总长度: {resp_len}")

        # 读取剩余的字节 (resp_len - 4)
        remaining_bytes = self.serial.read(resp_len - 4)
        if len(remaining_bytes) < (resp_len - 4):
            raise TimeoutError("读取响应体超时")

        full_response = header_bytes + remaining_bytes
        logger.debug(f"接收数据帧: {full_response.hex(' ').upper()}")

        # 4. 校验响应帧
        recv_checksum = full_response[-1]
        calc_checksum = self._calculate_checksum(full_response[:-1])
        if recv_checksum != calc_checksum:
            raise ValueError(f"响应校验和错误: 收到 0x{recv_checksum:02X}, 计算得到 0x{calc_checksum:02X}")

        # 状态检查：通常倒数第二字节（Checksum 之前）是下位机返回的错误/状态码
        status_code = full_response[-2]
        if status_code != 0x00:
            logger.warning(f"下位机返回状态码异常: 0x{status_code:02X}")

        return full_response

    def write_page_iic(self, port_str, slave_addr, start_addr, data, slot=0, board_type=0, page=0):
        """
        I2C 页写入操作 (对应 writePageIIC.vi)
        :param port_str: 端口类型字符串 ('SFP', 'XFP', 'QSFP')
        :param slave_addr: 器件地址 (0-255)
        :param start_addr: 寄存器起始地址 (0-255)
        :param data: 待写入的字节数据 (list 或 bytes)
        :param slot: 槽位号 (默认 0)
        :param board_type: 板卡类型 (默认 0)
        :param page: 页码 (默认 0)
        :return: True 代表写入成功，False 代表失败
        """
        port_id = self.PORT_TYPES.get(port_str.upper())
        if not port_id:
            raise ValueError(f"不支持的端口类型: {port_str}. 必须为 SFP, XFP 或 QSFP")

        # 字节数转换逻辑：如果写入 256 字节，SIZE 设为 0
        raw_size = len(data)
        if raw_size > 256:
            raise ValueError("单次写入长度不能超过 256 字节")
        
        size_param = 0 if raw_size == 256 else raw_size

        logger.info(f"准备写入 I2C 页 - 端口: {port_str}, 器件: 0x{slave_addr:02X}, "
                    f"起始地址: 0x{start_addr:02X}, 长度: {raw_size} 字节")

        try:
            # 写操作对应: sub_cmd = 1 (写SFP/XFP/QSFP命令), cmd_id = 3
            self.send_and_receive(
                slot=slot,
                board_type=board_type,
                sub_cmd=1,
                cmd_id=3,
                port_id=port_id,
                slave_addr=slave_addr,
                page=page,
                size=size_param,
                start_addr=start_addr,
                payload=data
            )
            logger.info("I2C 页写入成功")
            return True
        except Exception as e:
            logger.error(f"I2C 页写入失败: {e}")
            return False

    def read_iic(self, port_str, slave_addr, start_addr, bytes_to_read, slot=0, board_type=0, page=0):
        """
        I2C 数据读取操作 (对应 readIIC.vi)
        :param port_str: 端口类型字符串 ('SFP', 'XFP', 'QSFP')
        :param slave_addr: 器件地址 (0-255)
        :param start_addr: 寄存器起始地址 (0-255)
        :param bytes_to_read: 读取字节数 (1-256)
        :param slot: 槽位号 (默认 0)
        :param board_type: 板卡类型 (默认 0)
        :param page: 页码 (默认 0)
        :return: 读取到的字节数据 (bytes)
        """
        port_id = self.PORT_TYPES.get(port_str.upper())
        if not port_id:
            raise ValueError(f"不支持的端口类型: {port_str}. 必须为 SFP, XFP 或 QSFP")

        # 字节数转换逻辑：如果读取 256 字节，SIZE 设为 0
        if bytes_to_read > 256 or bytes_to_read <= 0:
            raise ValueError("读取长度必须在 1 ~ 256 字节之间")
            
        size_param = 0 if bytes_to_read == 256 else bytes_to_read

        logger.info(f"准备读取 I2C 数据 - 端口: {port_str}, 器件: 0x{slave_addr:02X}, "
                    f"起始地址: 0x{start_addr:02X}, 长度: {bytes_to_read} 字节")

        try:
            # 读操作对应: sub_cmd = 0 (读SFP/XFP/QSFP命令), cmd_id = 2
            resp = self.send_and_receive(
                slot=slot,
                board_type=board_type,
                sub_cmd=0,
                cmd_id=2,
                port_id=port_id,
                slave_addr=slave_addr,
                page=page,
                size=size_param,
                start_addr=start_addr
            )

            # 数据解析：读取数据从 Byte 12 开始，长度为实际读取的长度
            # 帧格式: [Header 12字节] + [Data N字节] + [Status 1字节] + [Checksum 1字节]
            data_start = 12
            data_end = data_start + bytes_to_read
            
            if len(resp) < data_end + 2:
                raise ValueError("收到的响应数据不足，无法提取完整数据")
                
            read_data = resp[data_start:data_end]
            logger.info(f"I2C 读取成功: {read_data.hex(' ').upper()}")
            return read_data
        except Exception as e:
            logger.error(f"I2C 读取失败: {e}")
            raise


def parse_int(val_str):
    """支持 10 进制或 16 进制字符串解析"""
    if val_str.lower().startswith("0x"):
        return int(val_str, 16)
    return int(val_str)


def main():
    parser = argparse.ArgumentParser(description="TBT IIC 读写程序 Python 命令行客户端")
    parser.add_argument("com", type=str, help="串口名称 (例如 COM3 或 /dev/ttyUSB0)")
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="子命令 (read 或 write)")
    
    # 读命令参数
    read_parser = subparsers.add_parser("read", help="读取 I2C 寄存器")
    read_parser.add_argument("port_type", type=str, choices=["SFP", "XFP", "QSFP"], help="接口类型")
    read_parser.add_argument("slave_addr", type=str, help="器件物理地址 (支持 10 进制或 0x 十六进制)")
    read_parser.add_argument("start_addr", type=str, help="寄存器起始偏移地址 (支持 10 进制或 0x 十六进制)")
    read_parser.add_argument("length", type=int, help="读取字节数 (1-256)")
    read_parser.add_argument("--page", type=str, default="0", help="页码 (PAGE_SELECT, 默认 0)")
    read_parser.add_argument("--slot", type=int, default=0, help="槽位号 (1-10，背板固定为 16，默认 0)")
    
    # 写命令参数
    write_parser = subparsers.add_parser("write", help="写入 I2C 寄存器")
    write_parser.add_argument("port_type", type=str, choices=["SFP", "XFP", "QSFP"], help="接口类型")
    write_parser.add_argument("slave_addr", type=str, help="器件物理地址 (支持 10 进制或 0x 十六进制)")
    write_parser.add_argument("start_addr", type=str, help="寄存器起始偏移地址 (支持 10 进制或 0x 十六进制)")
    write_parser.add_argument("data", type=str, help="待写入的数据，逗号分隔的十六进制字节串 (如: AA,BB,CC 或 01,02)")
    write_parser.add_argument("--page", type=str, default="0", help="页码 (PAGE_SELECT, 默认 0)")
    write_parser.add_argument("--slot", type=int, default=0, help="槽位号 (1-10，背板固定为 16，默认 0)")

    args = parser.parse_args()

    try:
        slave_addr = parse_int(args.slave_addr)
        start_addr = parse_int(args.start_addr)
        page = parse_int(args.page)
    except ValueError as e:
        logger.error(f"参数格式错误，请检查数值输入: {e}")
        sys.exit(1)

    # 运行控制器
    with TBTController(args.com) as tbt:
        if args.command == "read":
            try:
                data = tbt.read_iic(
                    port_str=args.port_type,
                    slave_addr=slave_addr,
                    start_addr=start_addr,
                    bytes_to_read=args.length,
                    slot=args.slot,
                    page=page
                )
                print(f"\n[读取结果]\n十六进制: {data.hex(' ').upper()}")
                try:
                    print(f"ASCII字符: {data.decode('ascii', errors='replace')}")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"读取操作执行失败: {e}")
                sys.exit(2)
                
        elif args.command == "write":
            # 解析待写入数据数组
            try:
                data_list = [int(x.strip(), 16) for x in args.data.split(',')]
            except ValueError as e:
                logger.error(f"待写入数据解析失败 (必须为逗号分隔的十六进制字节): {e}")
                sys.exit(1)

            success = tbt.write_page_iic(
                port_str=args.port_type,
                slave_addr=slave_addr,
                start_addr=start_addr,
                data=data_list,
                slot=args.slot,
                page=page
            )
            if success:
                print("\n[写入结果]\n操作成功")
            else:
                print("\n[写入结果]\n操作失败")
                sys.exit(2)

if __name__ == "__main__":
    main()
