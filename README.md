# proxy001-register

proxy001.com 全自动注册机 + 500MB 试用流量领取。**纯协议实现，无需浏览器、无需 GPU。**

跑完后直接给你可用的住宅代理凭证（网关 / 用户名 / 密码 / API Key / 有效期），
并保存成 JSON + 可读文本 + 代理清单三种格式。

---

## 它解决什么

proxy001 注册页有三道反爬：

| 关卡 | 站点做法 | 本仓库处理 |
|---|---|---|
| 发码前验人机 | Cloudflare Turnstile（`sitekey 0x4AAAAAAE9Z5ceCSJKdNDPs`，`action=ems_send`） | 交给打码站解，5–10 秒出 token |
| 注册时验指纹 | `reg_nonce` = RSA-OAEP 包裹 AES-GCM 加密的浏览器指纹 | 已复刻加密算法，纯 Python 构造 |
| 邮箱验证 | 6 位验证码 | YYDS 临时邮箱，实测 5–15 秒到达 |

打完这三关就直接拿到住宅代理账号。

---

## 快速开始（远程一键，推荐）

不用先下载仓库，一条命令搞定：自动检测 Python、建虚拟环境、装依赖、下载代码、启动交互界面。

### Windows

PowerShell 里执行：

```powershell
irm https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-windows.ps1 | iex
```

启动后会依次问你邮箱 key、打码 key、注册数量。

**如果不想交互**（例如批量脚本里调用），用环境变量：

```powershell
$env:YYDS_KEY="你的yyds key"
$env:SOLVER_KEY="你的打码站 key"
$env:PROXY001_ARGS="--count 5 --yes"
irm https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-windows.ps1 | iex
```

> `PROXY001_ARGS` 是必需的：`irm | iex` 这种执行方式下脚本拿不到命令行参数
> （PowerShell 的已知限制），只能通过环境变量传。

### Linux / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-linux.sh)
```

带参数：

```bash
YYDS_KEY="..." SOLVER_KEY="..." \
  bash <(curl -fsSL https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-linux.sh) \
  --count 5 --yes
```

安装位置默认 `~/.proxy001-register/`，可用 `WORKDIR` 覆盖：

```bash
WORKDIR=/opt/p001 bash <(curl -fsSL .../install-linux.sh)
```

更新代码：`FORCE_UPDATE=1 bash <(curl ...)`（Windows 用 `$env:FORCE_UPDATE="1"`）。

### 先看源码再运行（更稳妥）

```powershell
# Windows
irm https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-windows.ps1 -OutFile i.ps1
powershell -ExecutionPolicy Bypass -File i.ps1 --count 3
```

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-linux.sh -o i.sh
bash i.sh --count 3
```

### 本地直接跑

```bash
git clone https://github.com/zhacha222/proxy001-register.git
cd proxy001-register
pip install -r requirements.txt
python run.py
```

Windows 用户也可以双击 `start.bat`，Linux/macOS 用 `./start.sh`。

### 交互流程

```
[1/3] 邮箱服务 key（YYDS Mail）
  YYDS key: ****

[2/3] 打码站 key
  打码 key: ****

[3/3] 要注册多少个？
  数量: 3
```

输入完会先自检两个 key 并显示余额，确认后才开始注册。

### 参数

| 参数 | 说明 |
|---|---|
| `--count N` | 注册数量（默认交互询问，1–100） |
| `--yes` | 从环境变量读 key，全程不问 |
| `--interval S` | 每个账号之间间隔秒数（默认 3） |
| `--solver-base URL` | 打码站地址（默认 `https://cloudflare.pigeonw.com`） |

环境变量：

| 变量 | 说明 |
|---|---|
| `YYDS_KEY` | 邮箱服务 key |
| `SOLVER_KEY` | 打码站 key |
| `SOLVER_BASE` | 打码站地址 |
| `PROXY001_ARGS` | 远程一键时传参数用（如 `--count 5 --yes`） |
| `WORKDIR` | 安装目录（默认 `~/.proxy001-register`） |
| `FORCE_UPDATE=1` | 强制重新下载代码 |

---

---

## 输出示例

```
  ┌─ 账号 1/1 ─────────────────────────────────────────
  │
  │ 登录
  │   邮箱     ab12cd34@example.com
  │   密码     Px9!xxxxxxxxxQa
  │   API Key  00000000-0000-0000-0000-000000000000
  │
  │ 代理调用（账号密码认证）
  │   网关     us.proxy001.com:7878
  │   用户名   abcdef123456_custom_zone_us
  │   密码     pwxxxxxxxx
  │
  │   curl 示例
  │     curl -x "http://us.proxy001.com:7878" \
  │       -U "abcdef123456_custom_zone_us:pwxxxxxxxx" \
  │       https://ipinfo.io/json
  │
  │ 流量与有效期
  │   剩余流量 0.50GB
  │   有效期   5 hours 59 minutes   ← 试用流量限时，过期清零
  │   账户余额 $0.00   ← 付费余额，与试用流量分开
  └────────────────────────────────────────────────────
```

> 上面是脱敏示例。实际输出会是真实的邮箱、密码、API Key 和子账号账密。

结果同时写入 `output/`：

- `accounts-<时间>.json` — 完整结构化数据
- `accounts-<时间>.txt` — 上面那种可读格式（无颜色码）
- `proxies-<时间>.txt` — `网关:端口:用户名:密码:`，可直接喂给代理池工具

---

## 怎么用拿到的代理

网关固定一个入口 `us.proxy001.com:7878`，**地区靠用户名表达**，不用换连接。

### 用户名语法

```
<子账号>_custom_zone_<目标>
```

| 写法 | 效果 |
|---|---|
| `..._custom_zone_us` | 美国随机 |
| `..._custom_zone_jp` | 日本 |
| `..._custom_zone_hk` | 香港 |
| `..._custom_zone_us_st_georgia` | 美国 Georgia 州 |
| `..._custom_zone_us_city_atlanta` | 美国 Atlanta 市 |
| `..._custom_zone_GLOBAL` | 全球随机 |

粘性 IP（同一出口保持 N 分钟）：

```
..._custom_zone_us_ssid_23456789_time_30
```

> `_ssid_` 必须带，只写 `_time_` **不生效**（实测会一直轮换）。
> `_time_` 范围 1–180。

### curl

```bash
# HTTP 代理
curl -x "http://us.proxy001.com:7878" \
  -U "子账号_custom_zone_us:密码" \
  https://ipinfo.io/json

# SOCKS5
curl -x "socks5h://us.proxy001.com:7878" \
  -U "子账号_custom_zone_us:密码" \
  https://ipinfo.io/json
```

### Python

```python
import requests

USER = "子账号_custom_zone_us"
PWD  = "密码"
GW   = "us.proxy001.com:7878"
PROXY = f"http://{USER}:{PWD}@{GW}"

proxies = {"http": PROXY, "https": PROXY}
print(requests.get("https://ipinfo.io/json", proxies=proxies, timeout=30).json())
```

### 换国家

改用户名即可，**不需要新建连接**：

```python
for cc in ("us", "jp", "hk", "sg"):
    proxies = {"http": f"http://子账号_custom_zone_{cc}:密码@us.proxy001.com:7878"}
    print(cc, requests.get("http://ipinfo.io/country",
                           proxies=proxies, timeout=30).text.strip())
```

---

## ⚠ 必须知道的限制

1. **试用流量只有 6 小时有效期**，不是永久。文档里写的 "Traffic never expires"
   指的是**付费**流量。过期后账户余额仍是 `$0.00`，需充值才能继续用。

2. **大陆网络不能用**。站点会直接返回错误码 `423`，官方文档也写明
   「不支持在中国大陆使用」。所有调用必须从香港或海外出口发起。

3. **大洲写法不支持**。`_custom_zone_asia` / `_custom_zone_europe` 会返回
   `932 INVALID_TPL_LOCATION`，只能用国家码。

4. **API 提取链接需要 IP 白名单**。`/uapi/order/getIPlist` 会校验调用方公网 IP，
   未加白返回 `IP Whitelist Check Failed`。建议用上面的**账号密码模式**，
   不要走提取链接。

5. **一个打码额度 = 一个账号**。打码站只在成功出码时扣 1 次；失败不扣。

---

## 依赖

```
requests
cryptography
```

`cryptography` 只用于构造 `reg_nonce`（RSA-OAEP + AES-GCM）。

---

## 项目结构

```
proxy001-register/
├── run.py                  一键入口（交互式 CLI）
├── proxy001_register.py    核心库（打码 / 邮箱 / 加密 / 站点客户端）
├── install-windows.ps1     Windows 远程一键安装器（irm | iex）
├── install-linux.sh        Linux/macOS 远程一键安装器（curl | bash）
├── start.bat               Windows 本地双击启动
├── start.sh                Linux/macOS 本地启动
├── requirements.txt
├── LICENSE
└── output/                 运行结果（自动创建）
```

核心库可直接 import 做二次开发：

```python
from proxy001_register import CapSolver, YYDSMail, register_one

solver = CapSolver("https://cloudflare.pigeonw.com", "你的打码key")
mailer = YYDSMail("你的yyds key")
rec = register_one(solver, mailer, log=print)

if rec["ok"]:
    print(rec["email"], rec["info"]["sub_account"])
```

---

## 打码站接口契约

本仓库按以下契约实现（`CapSolver` 类）：

```http
Base: https://cloudflare.pigeonw.com
鉴权: Authorization: Bearer <key>   （或 X-API-Key / ?api_key=）
注意: 必须带非空 User-Agent，否则被 Cloudflare 拦

GET /turnstile?url=<页面>&sitekey=<key>&action=<action>&timeout=<10-180>
→ {"errorId":0,"taskId":"..."}

GET /result?id=<taskId>
→ {"status":"processing"}                                 处理中
→ {"errorId":0,"status":"ready","solution":{"token":"..."}}  成功
→ {"errorId":1,"errorCode":"ERROR_...","errorDescription":...} 失败

GET /balance
→ {"errorId":0,"balance":473,"quota_total":495,...}
```

**失败不扣额度**，可直接重试。以下错误码是硬失败（重试无意义）：
`ERROR_KEY_DOES_NOT_EXIST` / `ERROR_KEY_DENIED_ACCESS` /
`ERROR_ACCOUNT_EXPIRED` / `ERROR_ZERO_BALANCE` / `ERROR_DAILY_LIMIT`。

---

## 邮箱接口契约

YYDS Mail（`YYDSMail` 类）：

```http
Base:    https://maliapi.215.im/v1
鉴权:    X-API-Key: <key>

POST /accounts   {"localPart":"xxx","domain":"<域>"}
→ {"data":{"address":"xxx@域","id":"...","token":"..."}}

GET  /messages?address=<地址>&limit=10
→ {"data":{"messages":[{"subject","verificationCode":"123456","createdAt",...}]}}

DELETE /accounts/<id>   → 204
```

⚠ `/messages` **没有**「只取某时间之后」的参数，必须本地按 `createdAt` 过滤，
否则复用的邮箱会把上一轮的老验证码当新码返回。

---

## 技术细节（踩过的坑）

### 1. reg_nonce 的 PEM 解析

注册页里的公钥是 JS 字符串字面量，换行是**三个字符**（反斜杠、反斜杠、`n`），
另外 base64 的 `/` 被转义成 `\/`。两处都要还原，否则 `cryptography` 报
`InvalidByte(..., 92)`（92 = 反斜杠）。

### 2. reg_nonce 的构造顺序

```python
hex(RSA-OAEP(SHA-1)(AESKey)) + "." + hex(iv) + "." + hex(ciphertext)
```

`RSA-OAEP` 的 hash 和 MGF1 都是 **SHA-1**（不是 SHA-256），照着站点的
`encryptRegRandom()` 抄的。AES 是 **GCM**（不是 CBC），tag 附在密文尾部。

### 3. 指纹是伪造的

`_fp_snapshot()` 里的 canvas / webgl / audio hash 都是编的，只保证结构自洽。

**proxy001 目前（2026-11）不校验其真实性**，所以能过。但如果站点开始比对
hash 与 UA / GPU 的一致性，这条纯协议路径会**静默失效**（不会报错，只会
一直注册失败）。

届时退路是用指纹浏览器（Chromix，真实 GPU 的 WebGL）。本仓库刻意保持纯协议，
因为不需要 Windows + GPU，可以跑在 NAS / 服务器 / 青龙上。

### 4. 打码 token 是一次性的

发码被拒后不能复用旧 token，必须**重新打码**。`register_one()` 已按这个逻辑
实现了 `max_retries` 次循环。

---

## 合规声明

仅供**学习协议分析与自动化技术**使用。

- 该站点的服务条款可能禁止自动化注册，请自行判断风险并承担后果。
- 请勿用于批量囤号、转售或任何违法用途。
- 打码服务与邮箱服务均为第三方付费服务，请遵守各自条款。

作者不对使用本工具造成的任何后果负责。

---

## License

MIT
