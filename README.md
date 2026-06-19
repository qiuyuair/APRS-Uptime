# APRS Uptime

通过 APRS-IS 实时监听指定范围内的 APRS 台站，并将关键目标的在线状态推送到 [Uptime Kuma](https://github.com/louislam/uptime-kuma)。

## 功能

- 连接 APRS-IS，按地理范围过滤报文（服务端 `r/lat/lon/radius` 过滤）
- 实时显示范围内、时间窗口内有位置上报的台站列表
- 支持配置多个监控目标（呼号-SSID），定时向 Uptime Kuma Push 接口上报 `up` / `down`
- 可作为交互式终端工具运行，也可通过 systemd 常驻后台

## 工作原理

```
APRS-IS ──► aprs_nearby_watch.py ──► 终端输出（附近台站列表）
                      │
                      └──► Uptime Kuma Push API（各目标 up/down）
```

程序持续接收 APRS 位置报文，记录每个呼号（含 SSID）最近一次上报时间与坐标。对于 `kuma_push_config.py` 中配置的每个目标：

- 若在时间窗口内收到该呼号的位置报文 → 推送 `status=up`
- 若超时未收到 → 推送 `status=down`

## 环境要求

- Python 3.8+
- 可访问 APRS-IS（默认 `rotate.aprs2.net:14580`）
- 若启用 Kuma Push，需能访问 Uptime Kuma 的 Push 地址

## 安装

```bash
git clone https://github.com/qiuyuair/APRS-Uptime.git
cd APRS-Uptime

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

### 1. 主程序参数

编辑 `aprs_nearby_watch.py` 顶部的配置区：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CALLSIGN` | 连接 APRS-IS 使用的呼号 | `BG5VCU-17` |
| `PASSCODE` | APRS-IS 密码（只读可用 `-1`） | `-1` |
| `HOST` / `PORT` | APRS-IS 服务器 | `rotate.aprs2.net` / `14580` |
| `CENTER_LAT` / `CENTER_LON` | 监控中心点坐标 | 福州附近 |
| `RADIUS_KM` | 监控半径（公里） | `100` |
| `WINDOW_MINUTES` | 判定在线的时间窗口（分钟） | `15` |

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
- 若不创建 `kuma_push_config.py`，程序仍可正常运行，仅不做 Push 上报

#### 获取 Push URL

在 Uptime Kuma 中新建 **Push** 类型监控项，复制生成的 Push URL 即可。程序会自动追加：

- `status`：`up` 或 `down`
- `msg`：最近上报时间或离线说明
- `ping`：目标与中心点的距离（公里，仅 `up` 时）

## 运行

### 交互式（本地调试）

```bash
python aprs_nearby_watch.py
```

终端会实时刷新附近台站列表，按 `Ctrl+C` 退出。

### systemd 常驻服务（Linux）

1. 将项目部署到服务器，例如 `/home/ubuntu/APRS_Uptime`
2. 按需修改 `aprs-uptime.service` 中的路径与用户
3. 安装并启动：

```bash
sudo cp aprs-uptime.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aprs-uptime
```

查看日志：

```bash
journalctl -u aprs-uptime -f
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `aprs_nearby_watch.py` | 主程序 |
| `kuma_push_config.py` | Kuma Push 本地配置（**不纳入版本控制**） |
| `kuma_push_config.example.py` | 配置示例，复制后修改 |
| `aprs-uptime.service` | systemd 服务单元示例 |
| `requirements.txt` | Python 依赖 |

## 安全提示

`kuma_push_config.py` 含有 Uptime Kuma Push token，已加入 `.gitignore`，请勿提交到公开仓库。

## 许可证

MIT
