#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import os
import select
import socket
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import aprslib
from aprslib.exceptions import ConnectionDrop, ParseError, UnknownFormat

try:
    from kuma_push_config import KUMA_TARGETS, PUSH_INTERVAL_SECONDS
except ImportError:
    KUMA_TARGETS = []
    PUSH_INTERVAL_SECONDS = 300

try:
    from watch_config import (
        AIS_STALE_SECONDS,
        CALLSIGN,
        CENTER_LAT,
        CENTER_LON,
        HOST,
        PASSCODE,
        PORT,
        RADIUS_KM,
        RECONNECT_DELAY_SECONDS,
        SELECT_TIMEOUT_SECONDS,
        WATCHDOG_INTERVAL_SECONDS,
        WINDOW_MINUTES,
    )
except ImportError as e:
    raise SystemExit(
        "缺少 watch_config.py。请先执行：\n"
        "  cp watch_config.example.py watch_config.py\n"
        "然后编辑 watch_config.py 填入呼号、坐标等信息。"
    ) from e

SERVER_FILTER = f"r/{CENTER_LAT:.5f}/{CENTER_LON:.5f}/{RADIUS_KM}"


def utc_now():
    return datetime.now(timezone.utc)


def haversine_km(lat1, lon1, lat2, lon2):
    """计算两点球面距离（km）"""
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def print_result(reports, push_state=None):
    # 仅在交互式终端时清屏；systemd 服务下保留输出供 journalctl 查看
    if os.isatty(1):
        os.system("cls" if os.name == "nt" else "clear")

    now = utc_now()
    cutoff = now - timedelta(minutes=WINDOW_MINUTES)

    rows = []
    for report in reports.values():
        if report["seen"] >= cutoff:
            rows.append(report)

    rows.sort(key=lambda x: x["dist"])

    print("\n" + "=" * 90)
    print(
        f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"最近{WINDOW_MINUTES}分钟内，"
        f"{RADIUS_KM}km范围上报坐标用户：{len(rows)}"
    )
    if push_state and KUMA_TARGETS:
        for t in KUMA_TARGETS:
            target_from = t.get("from", "")
            state = push_state.get(target_from) or {}
            target_status = state.get("target_status")
            if target_status is None:
                report = reports.get(target_from)
                target_status = "up" if report and report["seen"] >= cutoff else "down"
            last_ok = state.get("last_ok")
            last_time = state.get("last_time")
            last_err = state.get("last_error")
            if last_time is not None:
                push_str = "成功" if last_ok else f"失败: {last_err}"
                print(f"监控 {target_from}: {target_status} | Push {push_str} @ {last_time.strftime('%H:%M:%S')} UTC")
            else:
                print(f"监控 {target_from}: {target_status} | Push 尚未执行")
    print("-" * 90)
    if not rows:
        print("暂无")
        return

    print(f"{'FROM':<14} {'DIST(km)':>9} {'LAT':>11} {'LON':>11} {'LAST_SEEN(UTC)':>25}")
    for info in rows:
        print(
            f"{info['from']:<14} "
            f"{info['dist']:>9.2f} "
            f"{info['lat']:>11.5f} "
            f"{info['lon']:>11.5f} "
            f"{info['seen'].strftime('%Y-%m-%d %H:%M:%S'):>25}"
        )


def prune_old_records(reports):
    cutoff = utc_now() - timedelta(minutes=WINDOW_MINUTES)
    expired = [src for src, report in reports.items() if report["seen"] < cutoff]
    for src in expired:
        del reports[src]


def do_kuma_push_one(reports, reports_lock, push_state, window_minutes, target_from, target_url):
    """对单个目标：根据最近是否在 window_minutes 内有上报，向 Kuma 推送 up/down。"""
    if not target_url or not target_from:
        return
    now = utc_now()
    cutoff = now - timedelta(minutes=window_minutes)
    with reports_lock:
        report = reports.get(target_from)
        if report and report["seen"] >= cutoff:
            status = "up"
            msg = f"last seen {report['seen'].strftime('%H:%M:%S')} UTC, dist {report['dist']:.1f}km"
            ping = report.get("dist")
        else:
            status = "down"
            msg = "no position in window" if not report else f"last {report['seen'].strftime('%H:%M:%S')} UTC"
            ping = None
    params = {"status": status, "msg": msg}
    if ping is not None:
        params["ping"] = f"{ping:.1f}"
    url = target_url.rstrip("/")
    if "?" in url:
        url += "&" + urllib.parse.urlencode(params)
    else:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            r.read()
        ok = True
    except Exception as e:
        ok = False
        msg = str(e)
    with reports_lock:
        if target_from not in push_state:
            push_state[target_from] = {}
        push_state[target_from]["last_ok"] = ok
        push_state[target_from]["last_time"] = now
        push_state[target_from]["target_status"] = status
        push_state[target_from]["last_error"] = None if ok else msg


def kuma_push_loop(reports, reports_lock, push_state):
    """后台线程：每 PUSH_INTERVAL_SECONDS 秒对全部监控目标各 Push 一次。"""
    while True:
        time.sleep(PUSH_INTERVAL_SECONDS)
        for t in KUMA_TARGETS:
            target_from = t.get("from", "")
            target_url = t.get("url", "")
            do_kuma_push_one(
                reports, reports_lock, push_state, WINDOW_MINUTES,
                target_from, target_url,
            )


def force_close_ais(ais):
    """尽量让阻塞中的 select/recv 立刻退出。"""
    if ais is None:
        return
    sock = getattr(ais, "sock", None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
    try:
        ais.close()
    except Exception:
        pass


def ais_watchdog(ais_ref, connection_state):
    """长时间无位置包时强制断开，触发重连。"""
    while True:
        time.sleep(WATCHDOG_INTERVAL_SECONDS)
        if not connection_state.get("connected"):
            continue
        last_activity = connection_state.get("last_activity")
        if not last_activity:
            continue
        if (utc_now() - last_activity).total_seconds() <= AIS_STALE_SECONDS:
            continue
        print(
            f"[{utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}] "
            f"APRS-IS 超过 {AIS_STALE_SECONDS}s 无位置包，强制重连..."
        )
        connection_state["connected"] = False
        force_close_ais(ais_ref[0])


def consume_ais_stream(ais, on_packet, connection_state):
    """
    替代 aprslib.consumer 的阻塞读取：
    - select 带超时，避免永久卡住
    - 看门狗关闭套接字后能干净退出
    """
    buf = b""
    try:
        ais.sock.setblocking(False)
    except socket.error as e:
        raise ConnectionDrop(f"connection dropped: {e}")

    while connection_state.get("connected"):
        try:
            ready, _, _ = select.select([ais.sock], [], [], SELECT_TIMEOUT_SECONDS)
        except (ValueError, OSError, socket.error) as e:
            raise ConnectionDrop(f"select failed: {e}")

        if not ready:
            continue

        try:
            chunk = ais.sock.recv(4096)
        except BlockingIOError:
            continue
        except socket.error as e:
            raise ConnectionDrop(f"recv failed: {e}")

        if not chunk:
            raise ConnectionDrop("connection dropped")

        buf += chunk

        while b"\r\n" in buf:
            line, buf = buf.split(b"\r\n", 1)
            if not line:
                continue
            if line.startswith(b"#"):
                continue
            try:
                packet = aprslib.parse(line)
            except (ParseError, UnknownFormat):
                continue
            except Exception:
                continue
            on_packet(packet)

    raise ConnectionDrop("watchdog closed connection")


def main():
    print("中心点:", f"{CENTER_LAT:.5f}, {CENTER_LON:.5f}")
    print("APRS-IS 主机:", f"{HOST}:{PORT}")
    print("服务端过滤:", SERVER_FILTER)
    print("输出模式: 实时刷新（每条有效报文刷新一次）")
    print("检测范围:", f"{RADIUS_KM}km")
    print("时间窗口:", f"{WINDOW_MINUTES}分钟")
    print("看门狗超时:", f"{AIS_STALE_SECONDS}s（按位置包计）")
    if KUMA_TARGETS:
        print("Kuma Push: 已启用，每", PUSH_INTERVAL_SECONDS, "秒上报，监控目标:", [t.get("from") for t in KUMA_TARGETS])
    else:
        print("Kuma Push: 未配置（编辑 kuma_push_config.py 中的 KUMA_TARGETS）")
    print("按 Ctrl+C 退出")

    reports = {}
    reports_lock = threading.Lock()
    push_state = {t.get("from", ""): {"last_ok": None, "last_time": None, "target_status": "unknown", "last_error": None} for t in KUMA_TARGETS}
    connection_state = {"connected": False, "last_activity": None}
    ais_ref = [None]

    if KUMA_TARGETS:
        push_thread = threading.Thread(
            target=kuma_push_loop,
            args=(reports, reports_lock, push_state),
            daemon=True,
        )
        push_thread.start()

    watchdog_thread = threading.Thread(
        target=ais_watchdog,
        args=(ais_ref, connection_state),
        daemon=True,
    )
    watchdog_thread.start()

    def on_packet(packet):
        lat = packet.get("latitude")
        lon = packet.get("longitude")
        src = packet.get("from")
        if lat is None or lon is None or not src:
            return

        # 位置包：刷新看门狗计时（不论是否进入监控列表）
        connection_state["last_activity"] = utc_now()

        lat = float(lat)
        lon = float(lon)
        dist = haversine_km(CENTER_LAT, CENTER_LON, lat, lon)
        if dist > RADIUS_KM:
            return

        with reports_lock:
            reports[src] = {
                "from": src,
                "lat": lat,
                "lon": lon,
                "dist": dist,
                "seen": utc_now(),
            }
            prune_old_records(reports)
            reports_snapshot = dict(reports)
            push_snapshot = dict(push_state)
        print_result(reports_snapshot, push_snapshot)

    while True:
        ais = aprslib.IS(CALLSIGN, passwd=PASSCODE, host=HOST, port=PORT)
        ais_ref[0] = ais
        try:
            connection_state["connected"] = False
            ais.connect(blocking=True, retry=RECONNECT_DELAY_SECONDS)
            ais.set_filter(SERVER_FILTER)
            connection_state["connected"] = True
            connection_state["last_activity"] = utc_now()
            print("已建立持续连接，开始实时接收...")

            consume_ais_stream(ais, on_packet, connection_state)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(
                f"[{utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}] "
                f"APRS-IS 连接中断: {e}"
            )
        finally:
            connection_state["connected"] = False
            force_close_ais(ais)
            ais_ref[0] = None

        print(f"{RECONNECT_DELAY_SECONDS}s 后重连...")
        time.sleep(RECONNECT_DELAY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出")
