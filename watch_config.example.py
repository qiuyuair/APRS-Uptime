#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APRS 监听配置示例。
复制为 watch_config.py 并填入你的呼号、坐标等本地信息。
"""

# APRS-IS 登录（只读监听可用 passcode "-1"）
CALLSIGN = "N0CALL-17"
PASSCODE = "-1"
HOST = "rotate.aprs2.net"
PORT = 14580

# 监控中心点（十进制度）
CENTER_LAT = 0.0
CENTER_LON = 0.0

# 监控半径（公里）与台站在线判定窗口（分钟）
RADIUS_KM = 100
WINDOW_MINUTES = 40

# 断线重连：连续无位置包达到 AIS_STALE_SECONDS 则强制重连
RECONNECT_DELAY_SECONDS = 15
AIS_STALE_SECONDS = 600
WATCHDOG_INTERVAL_SECONDS = 60
# select 超时：避免接收循环永久阻塞；超时本身不算断线
SELECT_TIMEOUT_SECONDS = 30
