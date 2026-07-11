# APRS Uptime

通过 APRS-IS 实时监听指定范围内的 APRS 台站，并将关键目标的在线状态推送到 [Uptime Kuma](https://github.com/louislam/uptime-kuma)。

## 功能

- 连接 APRS-IS，按地理范围过滤报文（服务端 `r/lat/lon/radius` 过滤）
- 实时显示范围内、时间窗口内有位置上报的台站列表
- 支持配置多个监控目标（呼号-SSID），定时向 Uptime Kuma Push 接口上报 `up` / `down`
- 断线自动重连；长时间无位置包时由看门狗强制重连
- 可作为交互式终端工具运行，也可通过 systemd 常驻后台

## 工作原理

```
APRS-IS ──► aprs_nearby_watch.py ──► 终端输出（附近台站列表）
                      │
                      └──► Uptime Kuma Push API（各目标 up/down）
```

程序持续接收 APRS **位置报文**，记录每个呼号（含 SSID）最近一次上报时间与坐标。对于 `kuma_push_config.py` 中配置的每个目标：

- 若在时间窗口内收到该呼号的位置报文 → 推送 `status=up`
- 若超时未收到 → 推送 `status=down`

仅位置包（含经纬度）参与在线判定；遥测等无坐标报文不影响 up/down。

### 断线与看门狗

- 连接异常断开后，等待 `RECONNECT_DELAY_SECONDS` 再重连
- 若连续 `AIS_STALE_SECONDS` 未收到任何**位置包**，看门狗强制断开并重连（用于处理 TCP 假连接）
- 接收循环使用带超时的 `select`，避免强制关闭套接字后主线程永久阻塞

## 环境要求

- Python 3.8+
- 可访问 APRS-IS（默认 `rotate.aprs2.net:14580`）
- 若启用 Kuma Push，需能访问 Uptime Kuma 的 Push 地址

## 全新部署

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

git clone https://github.com/qiuyuair/APRS-Uptime.git
cd APRS-Uptime

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# 必填：呼号、坐标等本地配置
cp watch_config.example.py watch_config.py
nano watch_config.py

# 可选：Uptime Kuma Push
cp kuma_push_config.example.py kuma_push_config.py
nano kuma_push_config.py
```

先手动验证：

```bash
source .venv/bin/activate
python aprs_nearby_watch.py
```

看到「已建立持续连接」后，可用 `Ctrl+C` 退出，再装 systemd。

## 配置

### 1. 监听参数（必填）

```bash
cp watch_config.example.py watch_config.py
```

编辑 `watch_config.py`：

| 变量 | 说明 | 示例 |
|------|------|------|
| `CALLSIGN` | 连接 APRS-IS 使用的呼号 | `N0CALL-17` |
| `PASSCODE` | APRS-IS 密码（只读可用 `-1`） | `-1` |
| `HOST` / `PORT` | APRS-IS 服务器 | `rotate.aprs2.net` / `14580` |
| `CENTER_LAT` / `CENTER_LON` | 监控中心点（十进制度） | 你的纬度 / 经度 |
| `RADIUS_KM` | 监控半径（公里） | `100` |
| `WINDOW_MINUTES` | 判定台站在线的时间窗口（分钟） | `40` |
| `RECONNECT_DELAY_SECONDS` | 断线后重连等待（秒） | `15` |
| `AIS_STALE_SECONDS` | 无位置包则强制重连（秒） | `600`（10 分钟） |
| `WATCHDOG_INTERVAL_SECONDS` | 看门狗检查间隔（秒） | `60` |
| `SELECT_TIMEOUT_SECONDS` | 接收循环 select 超时（秒） | `30` |

`watch_config.py` 含个人呼号与坐标，**已加入 `.gitignore`，请勿提交**。

### 2. Uptime Kuma Push（可选）

```bash
cp kuma_push_config.example.py kuma_push_config.py
```

编辑 `kuma_push_config.py`：

```python
PUSH_INTERVAL_SECONDS = 180

KUMA_TARGETS = [
    {"from": "BG5XXX-10", "url": "http://your-kuma-host:23000/api/push/your-push-token"},
    {"from": "BG5YYY-10", "url": "http://your-kuma-host:23000/api/push/another-token"},
]
```

- `from`：完整呼号含 SSID，须与 APRS 报文中的 `from` 字段一致
- `url`：Uptime Kuma 监控项的 Push 基础 URL（不含 `status` / `msg` / `ping` 参数）
- `PUSH_INTERVAL_SECONDS`：向 Kuma 推送的周期（秒）
- 若不创建 `kuma_push_config.py`，程序仍可正常运行，仅不做 Push 上报

#### 获取 Push URL

在 Uptime Kuma 中新建 **Push** 类型监控项，复制生成的 Push URL 即可。程序会自动追加：

- `status`：`up` 或 `down`
- `msg`：最近上报时间或离线说明
- `ping`：目标与中心点的距离（公里，仅 `up` 时）

## 运行

### 交互式（本地调试）

```bash
source .venv/bin/activate
python aprs_nearby_watch.py
```

终端会实时刷新附近台站列表，按 `Ctrl+C` 退出。

### systemd 常驻服务（Linux）

1. 确认 `aprs-uptime.service` 中的路径与用户与实际部署一致（默认示例：`/home/ubuntu/APRS-Uptime`）
2. 安装并启动：

```bash
sudo cp aprs-uptime.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aprs-uptime
```

更新代码后：

```bash
cd ~/APRS-Uptime
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart aprs-uptime
```

查看日志：

```bash
journalctl -u aprs-uptime -f
```

强制重连成功时，日志中通常会出现：`连接中断` → `15s 后重连` → `已建立持续连接`。

## 文件说明

| 文件 | 说明 |
|------|------|
| `aprs_nearby_watch.py` | 主程序 |
| `watch_config.py` | 本地监听配置（**不纳入版本控制**） |
| `watch_config.example.py` | 监听配置示例，复制后修改 |
| `kuma_push_config.py` | Kuma Push 本地配置（**不纳入版本控制**） |
| `kuma_push_config.example.py` | Kuma 配置示例，复制后修改 |
| `aprs-uptime.service` | systemd 服务单元示例 |
| `requirements.txt` | Python 依赖 |

## 安全提示

以下文件含个人或敏感信息，已加入 `.gitignore`，请勿提交到公开仓库：

- `watch_config.py`（呼号、坐标等）
- `kuma_push_config.py`（Uptime Kuma Push token）

## 许可证

MIT
