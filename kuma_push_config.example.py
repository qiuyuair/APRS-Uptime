#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Uptime Kuma Push 配置示例。
复制为 kuma_push_config.py 并填入你的 Push URL。
"""

# Push 上报间隔（秒）
PUSH_INTERVAL_SECONDS = 180

# 监控目标列表：每项为 {"from": "呼号-SSID", "url": "Push 基础 URL（不含 status/msg/ping）"}
KUMA_TARGETS = [
    {"from": "BG5XXX-10", "url": "http://your-kuma-host:23000/api/push/your-push-token"},
]
