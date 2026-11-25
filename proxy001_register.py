# -*- coding: utf-8 -*-
"""proxy001 全自动注册核心库（纯协议，无需浏览器）。

链路：
    YYDS 建箱 -> pigeonw 打 Turnstile -> /uapi/ems/send 发码
    -> YYDS 收码 -> 构造 reg_nonce -> /uapi/user/register 注册
    -> 登录 -> 抓 apiKey / 子账号账密 / 流量余额 / 有效期

对外只暴露 `register_one()` 与 `Proxy001Client`。
"""
import json
import os
import re
import sys
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = "https://proxy001.com"
REG_PATH = "/register"
LOGIN_PATH = "/login"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
SITEKEY_DEFAULT = "0x4AAAAAAE9Z5ceCSJKdNDPs"

AJAX = {"X-Requested-With": "XMLHttpRequest"}

# 需要重试的网络异常：TLS 抖动 (bad record mac)、连接重置、超时。
# 实测 proxy001 在部分出口会偶发 SSLV3_ALERT_BAD_RECORD_MAC，
# 连续重试即可通过，不重试会让整个注册流程白跑。
_RETRY_EXC = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def http_request(method, url, retries=4, backoff=1.5, **kw):
    """带指数退避的请求，只重试网络层抖动，不重试 HTTP 错误码。

    这样 4xx/5xx 的业务错误仍原样返回给调用方判断，
    TLS/连接类抖动则自动重试，避免偶发失败污染整批注册。
    """
    kw.setdefault("timeout", 45)
    last = None
    for attempt in range(1, retries + 1):
        try:
            return requests.request(method, url, **kw)
        except _RETRY_EXC as exc:
            last = exc
            if attempt >= retries:
                break
            time.sleep(backoff * attempt)
    raise last


# ----------------------------------------------------------------- 异常

class SolverError(Exception):
    """打码站失败（不可重试的错，如鉴权/余额）。"""


class CapSolverTransient(Exception):
    """打码站临时失败（可重试）。"""


# ------------------------------------------------------- Turnstile 打码

class CapSolver:
    """pigeonw Cloudflare solver 客户端。

    接口契约见仓库 README「打码站」一节。
    """

    def __init__(self, api_base, api_key, timeout=120, log=None):
        self.api = (api_base or "https://cloudflare.pigeonw.com").rstrip("/")
        self.key = (api_key or "").strip()
        self.timeout = timeout
        self.log = log or (lambda *a: None)
        if not self.key:
            raise SolverError("打码站 key 为空")

    def _headers(self):
        # 该站要求非空 UA，否则被 Cloudflare 拦；Authorization 三种写法等价
        return {"Authorization": "Bearer " + self.key, "User-Agent": UA}

    def balance(self):
        r = http_request("GET", self.api + "/balance", headers=self._headers(), timeout=30)
        if r.status_code >= 400:
            raise SolverError("余额查询失败 HTTP %d: %s" % (r.status_code, r.text[:150]))
        d = r.json()
        if d.get("errorId"):
            raise SolverError("%s: %s" % (d.get("errorCode"), d.get("errorDescription")))
        return d

    def solve_turnstile(self, url, sitekey, action=None, cdata=None, timeout=None):
        """返回 token 字符串。"""
        params = {"url": url, "sitekey": sitekey,
                  "timeout": int(timeout or self.timeout)}
        if action:
            params["action"] = action
        if cdata:
            params["cdata"] = cdata

        r = http_request("GET", self.api + "/turnstile", params=params,
                         headers=self._headers(), timeout=40)
        task = r.json()
        if task.get("errorId"):
            raise SolverError("%s: %s" % (task.get("errorCode"),
                                          task.get("errorDescription")))
        tid = task["taskId"]

        deadline = time.time() + params["timeout"] + 20
        while time.time() < deadline:
            time.sleep(1.5)
            rr = http_request("GET", self.api + "/result", params={"id": tid},
                              headers=self._headers(), timeout=40)
            res = rr.json()
            if res.get("status") == "processing":
                continue
            if res.get("errorId") == 0:
                sol = res.get("solution") or {}
                tok = sol.get("token") or ""
                if not tok:
                    raise CapSolverTransient("solution 无 token")
                self.log("[求解] %.2fs method=%s token_len=%d 计费=%s"
                         % (sol.get("elapsed_time", 0), sol.get("method"),
                            len(tok), res.get("billing_units")))
                return tok
            code = res.get("errorCode") or ""
            desc = res.get("errorDescription") or ""
            # 这些是硬失败，重试无意义
            if code in ("ERROR_KEY_DOES_NOT_EXIST", "ERROR_KEY_DENIED_ACCESS",
                        "ERROR_ACCOUNT_EXPIRED", "ERROR_ZERO_BALANCE",
                        "ERROR_DAILY_LIMIT"):
                raise SolverError("%s: %s" % (code, desc))
            raise CapSolverTransient("%s: %s" % (code, desc))
        raise CapSolverTransient("打码超时")


# ------------------------------------------------------------ YYDS 邮箱

class YYDSMail:
    """YYDS Mail 客户端（建箱 / 收码 / 删箱）。"""

    def __init__(self, api_key, base="https://maliapi.215.im/v1",
                 domain=None, log=None):
        self.base = base.rstrip("/")
        self.key = (api_key or "").strip()
        self.domain = domain
        self.log = log or (lambda *a: None)
        if not self.key:
            raise ValueError("YYDS key 为空")

    def _h(self, js=False):
        h = {"X-API-Key": self.key, "User-Agent": UA, "Accept": "application/json"}
        if js:
            h["Content-Type"] = "application/json"
        return h

    def me(self):
        r = http_request("GET", self.base + "/me", headers=self._h(), timeout=30)
        r.raise_for_status()
        return r.json().get("data") or {}

    def domains(self):
        r = http_request("GET", self.base + "/domains", headers=self._h(), timeout=30)
        r.raise_for_status()
        rows = r.json().get("data") or []
        return [x for x in rows if x.get("isVerified") and x.get("isMxValid")]

    def pick_domain(self):
        """优先用显式指定；否则用第一个 verified+MX 的域。"""
        if self.domain:
            return self.domain
        ds = self.domains()
        if not ds:
            raise RuntimeError("YYDS 无可用域名（verified + MX 均需为真）")
        return ds[0]["domain"]

    def create(self, prefix=None):
        local = prefix or ("px" + "".join(
            __import__("random").choice("0123456789") for _ in range(6)))
        body = {"localPart": local, "domain": self.pick_domain(),
                "autoDomainStrategy": "prefer_owned"}
        r = http_request("POST", self.base + "/accounts", data=json.dumps(body),
                          headers=self._h(js=True), timeout=40)
        if r.status_code >= 400:
            raise RuntimeError("建箱失败 HTTP %d: %s" % (r.status_code, r.text[:200]))
        d = r.json().get("data") or {}
        self.log("[邮箱] %s" % d.get("address"))
        return {"address": d["address"], "id": d["id"], "token": d.get("token")}

    def wait_code(self, address, since_ts, timeout=180, interval=4):
        """轮询直到拿到 since_ts 之后到达的验证码。

        注意：/v1/messages 没有「仅取某时间之后」的参数，必须本地按 createdAt
        过滤，否则复用的邮箱会把上一轮的老码当新码。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = self.messages(address)
            for m in msgs:
                created = str(m.get("createdAt") or "")
                code = str(m.get("verificationCode") or "")
                if code and created >= since_ts:
                    self.log("[收信] %s code=%s" % (m.get("subject", "")[:38], code))
                    return code
            time.sleep(interval)
        return ""

    def messages(self, address, limit=10):
        r = http_request("GET", self.base + "/messages",
                         params={"address": address, "limit": limit},
                         headers=self._h(), timeout=40)
        r.raise_for_status()
        return (r.json().get("data") or {}).get("messages") or []

    def delete(self, inbox_id):
        if not inbox_id:
            return
        try:
            http_request("DELETE", self.base + "/accounts/" + inbox_id,
                            headers=self._h(), timeout=30)
        except Exception:
            pass


# ------------------------------------------------- reg_nonce（站点加密）

def _fp_snapshot():
    """构造站点 fpSnapshot() 期望的指纹 JSON。

    ⚠ 这些 canvas/webgl/audio hash 是**伪造但结构自洽**的。proxy001 目前
    （2026-11）不校验其真实性，但一旦开始比对 hash 与 UA/GPU 的一致性，
    纯协议这条路会静默失效 —— 届时改用 Chromix 指纹浏览器。
    """
    return json.dumps({
        "canvas": "3f4a2b1c8d9e0f11",
        "webgl": {
            "hash": "a1b2c3d4e5f60718",
            "vendor": "Google Inc. (NVIDIA)",
            "renderer": ("ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 "
                         "vs_5_0 ps_5_0, D3D11)"),
        },
        "audio": "5d6e7f8091a2b3c4",
        "storageQuota": 299977031680,
        "errors": [],
        "mm": 14, "kc": 23, "paste": 0, "focus": 3, "blur": 2, "vis": 1,
        "elapsed": 18432,
    }, separators=(",", ":"), ensure_ascii=False)


def _load_pubkey(pem_js):
    """还原页面里的 PEM。

    HTML 原文里换行是**三个字符**：反斜杠、反斜杠、n（字面量 \\n）；
    另外 base64 的 / 被转义成 \\/。两处都要还原，否则 cryptography 报
    InvalidByte(..., 92)（92 = 反斜杠）。
    """
    bs = chr(92)
    pem = pem_js.replace(bs + bs + "n", "\n").replace(bs + "/", "/")
    pem = "\n".join(l.strip() for l in pem.strip().splitlines() if l.strip())
    return serialization.load_pem_public_key(pem.encode())


def build_reg_nonce(pub):
    """复刻站点 encryptRegRandom()：

        hex(RSA-OAEP(SHA-1)(AESKey)) . hex(iv) . hex(AES-GCM(指纹JSON))
    """
    data = _fp_snapshot().encode()
    aes_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ct = AESGCM(aes_key).encrypt(iv, data, None)
    enc_key = pub.encrypt(aes_key, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA1()),
        algorithm=hashes.SHA1(), label=None))
    return "%s.%s.%s" % (enc_key.hex(), iv.hex(), ct.hex())


# ------------------------------------------------------------- 站点客户端

class Proxy001Client:
    """proxy001 纯协议客户端：注册 / 登录 / 读取账号信息。"""

    def __init__(self, log=None):
        self.log = log or (lambda *a: None)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA,
                               "Accept-Language": "en-US,en;q=0.9"})
        # Session 也挂上重试：proxy001 会偶发 SSLV3_ALERT_BAD_RECORD_MAC，
        # TLS 握手层抖动对 urllib3 Retry 不可见，所以这里同时配 adapter 重试
        # 与 http_request() 两层兜底。
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            ad = HTTPAdapter(max_retries=Retry(
                total=4, connect=4, read=3, backoff_factor=1.2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET", "POST", "DELETE"])))
            self.s.mount("https://", ad)
            self.s.mount("http://", ad)
        except Exception:
            pass
    # ---- 页面 ----

    def _load_register(self):
        html = self.s.get(BASE + REG_PATH, timeout=40).text
        m_fp = re.search(r'fpChallenge\s*=\s*"([0-9a-f]+)"', html)
        m_pk = re.search(r'var regRandomPublicKey\s*=\s*"([^"]+)"', html)
        if not m_fp or not m_pk:
            raise RuntimeError("注册页结构变化：找不到 fpChallenge / regRandomPublicKey")
        return m_fp.group(1), m_pk.group(1)

    def preflight(self):
        """确认站点可达且 Turnstile sitekey 可解析。返回 (fp_challenge, pub, sitekey)。"""
        fp, pk = self._load_register()
        html = self.s.get(BASE + REG_PATH, timeout=40).text
        m_sk = re.search(r'turnstileSiteKey\s*=\s*"([^"]+)"', html)
        sitekey = m_sk.group(1) if m_sk else SITEKEY_DEFAULT
        return fp, _load_pubkey(pk), sitekey

    # ---- 发码 ----

    def send_code(self, email, token, fp_challenge=None):
        h = dict(AJAX)
        h.update({"Origin": BASE, "Referer": BASE + REG_PATH})
        r = self.s.post(BASE + "/uapi/ems/send",
                        data={"email": email, "event": "register",
                              "turnstile_token": token, "website": ""},
                        headers=h, timeout=45)
        try:
            return r.json()
        except Exception:
            return {"code": -1, "msg": "HTTP %d: %s" % (r.status_code, r.text[:120])}

    # ---- 注册 ----

    def register(self, email, password, code, fp_challenge, pub):
        nonce = build_reg_nonce(pub)
        h = dict(AJAX)
        h.update({"Origin": BASE, "Referer": BASE + REG_PATH})
        r = self.s.post(BASE + "/uapi/user/register",
                        data={"email": email, "password": password, "code": code,
                              "inviter_code": "", "fp_challenge": fp_challenge,
                              "reg_nonce": nonce},
                        headers=h, timeout=45)
        try:
            return r.json()
        except Exception:
            return {"code": -1, "msg": "HTTP %d: %s" % (r.status_code, r.text[:120])}

    # ---- 登录 ----

    def login(self, email, password):
        self.s.get(BASE + LOGIN_PATH, timeout=40)
        h = dict(AJAX)
        h.update({"Origin": BASE, "Referer": BASE + LOGIN_PATH})
        r = self.s.post(BASE + "/uapi/user/login",
                        data={"email": email, "password": password},
                        headers=h, timeout=45)
        d = r.json()
        if d.get("code") not in (1, 200):
            raise RuntimeError("登录失败: %s" % d.get("msg"))
        return d

    # ---- 账号信息 ----

    def api_key(self):
        d = self.s.get(BASE + "/index/user/dashboard.html", timeout=40).text
        m = re.search(r'id="apiKey"[^>]*value="([^"]+)"', d)
        return m.group(1) if m else None

    def child_account(self):
        """返回默认子账号 {username, password}（代理认证用）。"""
        h = dict(AJAX)
        h.update({"Referer": BASE + "/index/user/childAccounts"})
        r = self.s.get(BASE + "/uapi/child_account/index",
                       params={"page": 1, "limit": 20}, headers=h, timeout=40)
        d = r.json()
        rows = (d.get("data") or {}).get("rows") or []
        if not rows:
            return None
        # 取 enabled 的第一条
        for row in rows:
            if row.get("status") == 1:
                return {"username": row.get("username"),
                        "password": row.get("password")}
        return {"username": rows[0].get("username"),
                "password": rows[0].get("password")}

    def gateway(self):
        """代理网关 host:port（默认 us.proxy001.com:7878）。"""
        t = self.s.get(BASE + "/index/user/getagent", timeout=40).text
        m = re.search(r'id="host_port"[^>]*value="([^"]*)"', t)
        return m.group(1) if m and m.group(1) else "us.proxy001.com:7878"

    def traffic(self):
        """从 dashboard 抓剩余流量与到期信息。"""
        d = self.s.get(BASE + "/index/user/dashboard.html", timeout=40).text
        txt = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", d)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt)
        out = {}
        m = re.search(r"Data Remaining\s*([\d.]+\s*[GMK]B)", txt)
        out["remaining"] = m.group(1).strip() if m else None
        m = re.search(r"remaining time:\s*([0-9a-zA-Z ]+?)(?:Details|$)", txt, re.I)
        out["remaining_time"] = m.group(1).strip() if m else None
        m = re.search(r"Account Balance[：:]\s*\$?([\d.]+)", txt)
        out["balance"] = m.group(1) if m else None
        return out

    def collect(self):
        """一次性抓齐 apiKey / 子账号 / 网关 / 流量。"""
        info = {}
        try:
            info["api_key"] = self.api_key()
        except Exception as e:
            info["api_key"] = None
            self.log("[!] 读 apiKey 失败: %s" % str(e)[:60])
        try:
            info["sub_account"] = self.child_account()
        except Exception as e:
            info["sub_account"] = None
            self.log("[!] 读子账号失败: %s" % str(e)[:60])
        try:
            info["gateway"] = self.gateway()
        except Exception:
            info["gateway"] = "us.proxy001.com:7878"
        try:
            info.update(self.traffic())
        except Exception as e:
            self.log("[!] 读流量失败: %s" % str(e)[:60])
        return info


# --------------------------------------------------------------- 单次注册

def register_one(solver, mailer, password=None, log=None, max_retries=3):
    """跑完一个账号的完整链路。

    返回 dict：成功含 email/password/info；失败含 error 与 stage。
    """
    log = log or (lambda *a: None)
    password = password or ("Px9!" + "".join(
        __import__("random").choice("abcdefghjkmnpqrstuvwxyz23456789")
        for _ in range(9)) + "Qa")
    out = {"email": None, "password": password, "stage": "init"}

    box = mailer.create()
    out["email"] = box["address"]
    email = box["address"]

    try:
        cli = Proxy001Client(log=log)
        out["stage"] = "preflight"
        fp_challenge, pub, sitekey = cli.preflight()

        # 发码：打码失败/发码失败都重试（token 一次性，需重新打）
        sent = False
        last = None
        for attempt in range(1, max_retries + 1):
            out["stage"] = "solve"
            try:
                tok = solver.solve_turnstile(BASE + REG_PATH, sitekey,
                                             action="ems_send")
            except CapSolverTransient as e:
                last = "打码临时失败: %s" % str(e)[:110]
                log("[!] %s（第 %d 次）" % (last, attempt))
                time.sleep(3)
                continue

            out["stage"] = "send_code"
            since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            resp = cli.send_code(email, tok, fp_challenge)
            if resp.get("code") in (1, 200):
                sent = True
                break
            last = "发码被拒: %s" % resp.get("msg")
            log("[!] %s（第 %d 次）" % (last, attempt))
            time.sleep(3)

        if not sent:
            out["error"] = last or "发码失败"
            out["stage"] = "send_code"
            return out

        out["stage"] = "wait_code"
        code = mailer.wait_code(email, since, timeout=180)
        if not code:
            out["error"] = "180s 内未收到验证码"
            return out
        out["verify_code"] = code

        out["stage"] = "register"
        resp = cli.register(email, password, code, fp_challenge, pub)
        if resp.get("code") not in (1, 200):
            out["error"] = "注册被拒: %s" % resp.get("msg")
            return out
        out["ok"] = True
        out["stage"] = "collect"

        cli.login(email, password)
        out["info"] = cli.collect()
        return out

    finally:
        # 邮箱保留（便于人工查收件），仅记录 id 供上层决定是否清理
        out["inbox_id"] = box.get("id")


# -------------------------------------------------------------------- CLI
if __name__ == "__main__":
    def _log(*a):
        print(*a, flush=True)

    # 从环境变量读 key，绝不硬编码（本仓库是 public）
    k_mail = os.environ.get("YYDS_KEY", "").strip()
    k_cap = os.environ.get("SOLVER_KEY", "").strip()
    if not k_mail or not k_cap:
        _log("请先设置环境变量 YYDS_KEY 与 SOLVER_KEY")
        sys.exit(2)

    sol = CapSolver(os.environ.get("SOLVER_BASE",
                                   "https://cloudflare.pigeonw.com"),
                    k_cap, log=_log)
    _log("[余额]", json.dumps(sol.balance(), ensure_ascii=False))
    mailer = YYDSMail(k_mail, log=_log)
    r = register_one(sol, mailer, log=_log)
    _log(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)
