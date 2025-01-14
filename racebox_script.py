#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# @author by wangcw @ 2025
# @generate at 2025/1/14 15:59
# comment:

import asyncio
from bleak import BleakScanner, BleakClient
from loguru import logger


import asyncio
import struct
from datetime import datetime
from bleak import BleakScanner, BleakClient
import os
import configparser
import psycopg2
import psycopg2.extras as extras
import uuid
from loguru import logger
import math

# 数据库连接定义
config = configparser.ConfigParser()
config.read("conf/db.cnf")

pg_host = config.get("racebox", "host")
pg_database = config.get("racebox", "database")
pg_user = config.get("racebox", "user")
pg_password = config.get("racebox", "password")
pg_port = int(config.get("racebox", "port"))
amap_key = config.get("amap", "amap_key")

# 日志配置
logDir = os.path.expanduser("log/")
if not os.path.exists(logDir):
    os.mkdir(logDir)
logFile = os.path.join(logDir, "racebox.log")
# logger.remove(handler_id=None)

logger.add(
    logFile,
    colorize=True,
    rotation="1 days",
    retention="3 days",
    format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {message}",
    backtrace=True,
    diagnose=True,
    level="INFO",
)

# RaceBox 接口定义 UUIDs
UART_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
NMEA_TX_UUID = "00001103-0000-1000-8000-00805f9b34fb"
DOWNLOAD_COMMAND = bytes([0xB5, 0x62, 0xFF, 0x23, 0x00, 0x00, 0x22, 0x65])  # Command to initiate data download

# Define the bounding box for China
LAT_MIN, LAT_MAX = 3.52, 53.33
LON_MIN, LON_MAX = 73.40, 135.25

# GC02J 坐标转换参数
x_pi = math.pi * 3000.0 / 180.0
a = 6378245.0
ee = 0.00669342162296594323

ins_data = """insert into lc_racebox(itow, imp_stamp, year, month, day, hour, minute, second, time_accuracy, nanoseconds,  
            fix_status, numberof_svs, longitude, latitude, wgs_altitude, msl_altitude, horizontal_accuracy, 
            vertical_accuracy, speed, heading, speed_accuracy, heading_accuracy, pdop, gforce_x, gforce_y, gforce_z, 
            rotation_rate_x, rotation_rate_y, rotation_rate_z) values %s on conflict (itow) do update set 
            year=excluded.year, month=excluded.month, day=excluded.day, hour=excluded.hour, minute=excluded.minute, 
            second=excluded.second, time_accuracy=excluded.time_accuracy, nanoseconds=excluded.nanoseconds, 
            fix_status=excluded.fix_status, numberof_svs=excluded.numberof_svs, longitude=excluded.longitude, 
            latitude=excluded.latitude, wgs_altitude=excluded.wgs_altitude, msl_altitude=excluded.msl_altitude, 
            horizontal_accuracy=excluded.horizontal_accuracy, vertical_accuracy=excluded.vertical_accuracy, 
            speed=excluded.speed, heading=excluded.heading, speed_accuracy=excluded.speed_accuracy, 
            heading_accuracy=excluded.heading_accuracy, pdop=excluded.pdop, gforce_x=excluded.gforce_x, 
            gforce_y=excluded.gforce_y, gforce_z=excluded.gforce_z, rotation_rate_x=excluded.rotation_rate_x, 
            rotation_rate_y=excluded.rotation_rate_y, rotation_rate_z=excluded.rotation_rate_z;
            """

ins_imp = """insert into imp_racebox(imp_stamp, file_name, duration) values (%s, %s, %s);
          """

# 上次连接设备文件
DEVICE_MEMORY_FILE = "../conf/last_device.json"

# 本次插入数据uuid
time_uuid = uuid.uuid1()

# 建立数据库连接
con = psycopg2.connect(database=pg_database,
                       user=pg_user,
                       password=pg_password,
                       host=pg_host,
                       port=pg_port)

psycopg2.extras.register_uuid()


def _transformlat(lng, lat):
    ret = (-100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat +
           0.1 * lng * lat + 0.2 * math.sqrt(math.fabs(lng)))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 *
            math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 *
            math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 *
            math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret

def _transformlng(lng, lat):
    ret = (300.0 + lng + 2.0 * lat + 0.1 * lng * lng +
           0.1 * lng * lat + 0.1 * math.sqrt(math.fabs(lng)))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 *
            math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 *
            math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 *
            math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret

def out_of_china(lng, lat):
    return not (lng > 73.40 and lng < 135.25 and lat > 3.52 and lat < 53.55)

def wgs84_to_gcj02(lng, lat):
    if out_of_china(lng, lat):
        return [lng, lat]
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    mglat = lat + dlat
    mglng = lng + dlng
    return [mglng, mglat]


def format_filename(in_first_record, in_last_record):
    """生成文件名"""
    first_year = in_first_record[2]
    first_month = f"{in_first_record[3]:02d}"
    first_day = f"{in_first_record[4]:02d}"
    first_hour = f"{in_first_record[5]:02d}"
    first_minute = f"{in_first_record[6]:02d}"
    first_second = f"{in_first_record[7]:02d}"
    last_year = in_last_record[2]
    last_month = f"{in_last_record[3]:02d}"
    last_day = f"{in_last_record[4]:02d}"
    last_hour = f"{in_last_record[5]:02d}"
    last_minute = f"{in_last_record[6]:02d}"
    last_second = f"{in_last_record[7]:02d}"
    first_timestamp = f"{first_year}{first_month}{first_day}{first_hour}{first_minute}{first_second}"
    last_timestamp = f"{last_year}{last_month}{last_day}{last_hour}{last_minute}{last_second}"
    return f"{first_timestamp}_{last_timestamp}"


def parse_message(packet):
    """处理二进制数据"""
    payload = packet[6:86]
    parsed_data = struct.unpack('<I H B B B B B B I i B B B B i i i i I I i i I I H B B h h h h h h', payload[:80])
    lng, lat = wgs84_to_gcj02((parsed_data[14] / 1e7), (parsed_data[15] / 1e7))
    if int(parsed_data[10]) != 0:
        record = (
            parsed_data[0],  # "iTOW"
            time_uuid,  # 导入标签
            parsed_data[1],  # "Year"
            parsed_data[2],  # "Month"
            parsed_data[3],  # "Day"
            parsed_data[4],  # "Hour"
            parsed_data[5],  # "Minute"
            parsed_data[6],  # "Second"
            parsed_data[8],  # "Time Accuracy"
            parsed_data[9],  # "Nanoseconds"
            parsed_data[10],  # "Fix Status"
            parsed_data[13],  # "Number of SVs"
            lng,  # "Longitude"
            lat,  # "Latitude"
            parsed_data[16] / 1000,  # "WGS Altitude"
            parsed_data[17] / 1000,  # "MSL Altitude"
            parsed_data[18] / 1000,  # "Horizontal Accuracy"
            parsed_data[19] / 1000,  # "Vertical Accuracy"
            parsed_data[20] / 100 * 60,  # "Speed"
            parsed_data[21] / 100000,  # "Heading"
            parsed_data[22],  # "Speed Accuracy"
            parsed_data[23] / 1e5,  # "Heading Accuracy"
            parsed_data[24],  # "PDOP"
            parsed_data[27] / 1000,  # "G-Force X"
            parsed_data[28] / 1000,  # "G-Force Y"
            parsed_data[29] / 1000,  # "G-Force Z"
            parsed_data[30] / 100,  # "Rotation rate X"
            parsed_data[31] / 100,  # "Rotation rate Y"
            parsed_data[32] / 100  # "Rotation rate Z"
        )
        return record


def validate_checksum(buffer):
    """根据结构协议校验数据"""
    ck_a, ck_b = 0, 0
    for byte in buffer[2:-2]:
        ck_a = (ck_a + byte) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return ck_a == buffer[-2] and ck_b == buffer[-1]


def insert_db(in_sql, in_data):
    try:
        cur = con.cursor()
        cur.execute(in_sql, in_data)
        con.commit()
    except Exception as e:
        logger.error(e)
    finally:
        cur.close()


async def connect_and_download(device):
    """建立已扫描连接并下载数据"""
    session_data = []
    buffer = bytearray()
    total_records = 0
    download_complete = asyncio.Event()
    session_num = 0
    down_start_time = datetime.now()
    session_start_time = datetime.now()
    first_record = None
    last_record = None

    async with (BleakClient(device.address, timeout=20) as client):
        try:
            await client.disconnect()
            await client.connect()

            services = client.services

            if UART_UUID not in [str(service.uuid) for service in services]:
                logger.error(f"设备 {device.name} 无 UART 服务！")
                return

            def notification_handler(sender, data):
                nonlocal buffer, session_data, total_records, session_num, down_start_time, session_start_time, first_record, last_record
                buffer.extend(data)

                # 处理传输数据
                while len(buffer) >= 8:
                    if buffer[:2] == bytes([0xB5, 0x62]):
                        message_class, message_id = buffer[2], buffer[3]
                        packet_length = struct.unpack('<H', buffer[4:6])[0]
                        full_packet_length = packet_length + 8

                        if len(buffer) < full_packet_length:
                            break

                        if validate_checksum(buffer[:full_packet_length]):
                            if message_class == 0xFF:
                                if message_id == 0x23:  # 开始下载
                                    total_records = struct.unpack('<I', buffer[6:10])[0]
                                    logger.info(f"总计 {total_records} 条记录")
                                elif message_id == 0x21:  # 历史数据
                                    record = parse_message(buffer[:full_packet_length])
                                    if record:
                                        session_data.append(record)
                                        if first_record is None:
                                            first_record = record
                                        last_record = record
                                elif message_id == 0x01:  # 实时数据
                                    record = parse_message(buffer[:full_packet_length])
                                    if record:
                                        session_data.append(record)
                                        if first_record is None:
                                            first_record = record
                                    last_record = record
                                elif message_id == 0x02:
                                    logger.info(
                                        f"下载完成，耗时 {(datetime.now() - down_start_time).total_seconds()} 秒！")
                                    download_complete.set()
                                elif message_id == 0x26:
                                    if first_record:
                                        session_num += 1
                                        duration = (datetime.now() - session_start_time).total_seconds()
                                        file_name = format_filename(first_record, last_record)
                                        imp_data = (time_uuid, file_name, duration)
                                        insert_db(ins_imp, imp_data)
                                        logger.info(f"已处理第{session_num}段数据，耗时 {duration} 秒！")
                                    session_start_time = datetime.now()
                                    first_record = None
                            buffer = buffer[full_packet_length:]

            await client.start_notify(TX_CHAR_UUID, notification_handler)
            await client.write_gatt_char(RX_CHAR_UUID, DOWNLOAD_COMMAND)
            logger.info(f"正在从设备 {device.name} 下载数据...")

            # 等待下载完成
            await download_complete.wait()
            await client.stop_notify(TX_CHAR_UUID)
        except Exception as e:
            logger.error(e)
        finally:
            await client.disconnect()

    # 保存数据
    if session_data:
        try:
            insert_start_time = datetime.now()
            cur = con.cursor()
            extras.execute_values(cur, ins_data, session_data, page_size=1000)
            con.commit()
            logger.info(f"定位数据入库成功，耗时 {(datetime.now() - insert_start_time).total_seconds()} 秒！")
        except Exception as e:
            logger.error(e)
        finally:
            cur.close()


async def download_racebox_data(callback):
    """扫描蓝牙设备并下载数据"""
    devices = await BleakScanner.discover()
    racebox_devices = [device for device in devices if device.name and "RaceBox" in device.name]

    if racebox_devices:
        logger.info(f"发现 {len(racebox_devices)} 个 RaceBox 设备.")
        for device in racebox_devices:
            try:
                logger.info(f"尝试连接设备: {device.name}")
                async with BleakClient(device.address) as client:
                    if not client.is_connected:
                        raise Exception("设备连接失败")
                    logger.info(f"已连接到设备: {device.name}")
                    start_time = datetime.now()
                    asyncio.run(connect_and_download(device))
                    logger.info(f"所有操作完成，总计耗时 {(datetime.now() - start_time).total_seconds()} 秒！")
                    break
            except Exception as e:
                logger.error(f"连接设备失败: {device.name}: {e}")
    else:
        callback("未找到 RaceBox 设备")
