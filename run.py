# -*- coding: utf-8 -*-
"""proxy001 一键注册机（交互式）。

运行后依次询问：
    1) YYDS 邮箱 key
    2) 打码站 key
    3) 注册多少个

然后逐个注册，每个账号的成功信息（调用方式、key、有效期等）都会
打印到控制台，并保存为 JSON + 可读文本 + 代理清单。

用法：
    python run.py                     交互模式
    python run.py --count 5           跳过数量询问
    python run.py --count 3 --yes     全部使用环境变量里的 key，不再询问
环境变量（可选，避免每次输入）：
    YYDS_KEY / SOLVER_KEY / SOLVER_BASE
"""
import argparse
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from proxy001_register import (  # noqa: E402
    CapSolver, CapSolverTransient, SolverError, YYDSMail, register_one,
)

OUT_DIR = os.path.join(HERE, "output")
DEFAULT_SOLVER_BASE = "https://cloudflare.pigeonw.com"

C = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[36m", "gray": "\033[90m",
}


def _color_ok():
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        # 老 conhost 可能不支持 ANSI，开启 VT
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            return False
    return True


USE_C = _color_ok()


def c(text, color):
    if not USE_C:
        return text
    return C.get(color, "") + str(text) + C["reset"]


def log(msg=""):
    print(msg, flush=True)


def hr(ch="─", n=68):
    log(c(ch * n, "gray"))


def title(text):
    hr("═")
    log(c("  " + text, "bold"))
    hr("═")


def _stdin_usable():
    """判断 stdin 能不能读。

    远程执行（如 PowerShell 的 `irm ... | iex`、bash 的 `curl ... | bash`）
    时 stdin 可能已被管道占用或指向空设备，此时 input()/getpass() 会立刻 EOF。
    提前检测出来，给一句明确提示，比抛一堆 traceback 有用。
    """
    try:
        return not sys.stdin.isatty() or True  # 非 tty 也可能可读（重定向），继续尝试
    except Exception:
        return False


def ask(prompt, default=None, secret=False):
    """读一行输入；secret=True 时尽量不回显，无 TTY 时自动降级为普通读入。"""
    suffix = "" if not default else c(" [默认 %s]" % default, "gray")
    for _ in range(5):
        try:
            if secret:
                # getpass 在无 TTY / stdin 被占用时会抛 GetPassWarning 或直接 EOF，
                # 这里必须兜底，否则远程一键执行会「什么都没说就退出」。
                try:
                    import getpass
                    v = getpass.getpass("  " + prompt + suffix + ": ").strip()
                except Exception:
                    v = input("  " + prompt + suffix + ": ").strip()
            else:
                v = input("  " + prompt + suffix + ": ").strip()
        except (EOFError, KeyboardInterrupt):
            log("")
            if default:
                log(c("  未读到输入，使用默认值。", "yellow"))
                return default
            log(c("  未读到输入（stdin 不可用）。", "red"))
            log(c("  远程执行时请改用环境变量或 --yes，例如：", "gray"))
            log(c("    $env:YYDS_KEY=\"...\"; $env:SOLVER_KEY=\"...\"; "
                  "$env:PROXY001_ARGS=\"--count 3 --yes\"", "gray"))
            sys.exit(130)
        if v:
            return v
        if default:
            return default
        log(c("  不能为空，请重新输入。", "red"))
    return default or ""


def ask_int(prompt, default=1, lo=1, hi=100):
    while True:
        v = ask(prompt, default=str(default))
        try:
            n = int(v)
        except ValueError:
            log(c("  请输入数字。", "red"))
            continue
        if not (lo <= n <= hi):
            log(c("  请输入 %d - %d 之间的数字。" % (lo, hi), "red"))
            continue
        return n


def ask_yes(prompt, default="n"):
    v = ask(prompt + " (y/n)", default=default).lower()
    return v in ("y", "yes", "1", "是")


# ------------------------------------------------------------- 输出格式化

def format_account(i, total, rec):
    """把一个账号的完整信息整理成可打印文本。"""
    info = rec.get("info") or {}
    sub = info.get("sub_account") or {}
    gw = info.get("gateway") or "us.proxy001.com:7878"
    host, _, port = gw.partition(":")
    user = sub.get("username") or ""
    pwd = sub.get("password") or ""
    lines = []

    lines.append("")
    lines.append(c("  ┌─ 账号 %d/%d ─────────────────────────────────────────" % (i, total), "bold"))
    lines.append("  │")
    lines.append("  │ " + c("登录", "blue"))
    lines.append("  │   邮箱     " + rec.get("email", ""))
    lines.append("  │   密码     " + rec.get("password", ""))
    lines.append("  │   API Key  " + (info.get("api_key") or c("(未取到)", "yellow")))
    lines.append("  │")
    lines.append("  │ " + c("代理调用（账号密码认证）", "blue"))
    if user and pwd:
        lines.append("  │   网关     " + gw)
        lines.append("  │   用户名   " + user + c("_custom_zone_us", "gray"))
        lines.append("  │   密码     " + pwd)
        lines.append("  │")
        lines.append("  │   " + c("curl 示例", "gray"))
        lines.append("  │     curl -x \"http://%s\" \\" % gw)
        lines.append("  │       -U \"%s_custom_zone_us:%s\" \\" % (user, pwd))
        lines.append("  │       https://ipinfo.io/json")
        lines.append("  │")
        lines.append("  │   " + c("Python 示例", "gray"))
        lines.append("  │     proxies = {\"http\": \"http://%s_custom_zone_us:%s@%s\","
                     % (user, pwd, gw))
        lines.append("  │                \"https\": \"http://%s_custom_zone_us:%s@%s\"}"
                     % (user, pwd, gw))
    else:
        lines.append("  │   " + c("⚠ 未取到子账号账密，请登录后台查看", "yellow"))
    lines.append("  │")
    lines.append("  │ " + c("流量与有效期", "blue"))
    lines.append("  │   剩余流量 " + str(info.get("remaining") or "?"))
    lines.append("  │   有效期   " + str(info.get("remaining_time") or "?")
                 + c("   ← 试用流量限时，过期清零", "yellow"))
    lines.append("  │   账户余额 $" + str(info.get("balance") or "0.00")
                 + c("   ← 付费余额，与试用流量分开", "gray"))
    lines.append("  │")
    lines.append("  │ " + c("地区定向语法（改用户名即可，无需换连接）", "gray"))
    lines.append("  │   ..._custom_zone_us        美国（含 st_/city_ 细分）")
    lines.append("  │   ..._custom_zone_jp        日本")
    lines.append("  │   ..._custom_zone_hk        香港")
    lines.append("  │   ..._custom_zone_us_ssid_<8位>_time_<1-180>   粘性IP")
    lines.append("  │   " + c("注意：_asia/_europe 大洲写法不支持（返回 932），只能用国家码", "yellow"))
    lines.append("  └" + "─" * 60)
    return "\n".join(lines)


def save_outputs(results, meta):
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")

    # 1) 完整 JSON
    p_json = os.path.join(OUT_DIR, "accounts-%s.json" % ts)
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "accounts": results}, f,
                  ensure_ascii=False, indent=2)

    # 2) 可读文本
    p_txt = os.path.join(OUT_DIR, "accounts-%s.txt" % ts)
    with open(p_txt, "w", encoding="utf-8") as f:
        f.write("proxy001 注册结果  %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        f.write("=" * 68 + "\n")
        for i, r in enumerate(results, 1):
            if r.get("ok"):
                plain = format_account(i, len(results), r)
                # 去掉 ANSI
                import re
                plain = re.sub(r"\033\[[0-9;]*m", "", plain)
                f.write(plain + "\n")
            else:
                f.write("\n  [%d] 失败: %s\n      stage=%s email=%s\n"
                        % (i, r.get("error"), r.get("stage"), r.get("email")))

    # 3) 代理清单（host:port:user:pass，兼容常见代理池工具）
    p_proxy = os.path.join(OUT_DIR, "proxies-%s.txt" % ts)
    with open(p_proxy, "w", encoding="utf-8") as f:
        for r in results:
            if not r.get("ok"):
                continue
            info = r.get("info") or {}
            sub = info.get("sub_account") or {}
            gw = info.get("gateway") or "us.proxy001.com:7878"
            if sub.get("username"):
                f.write("%s:%s:%s:%s\n" % (gw, sub["username"],
                                           sub["password"], ""))
    return p_json, p_txt, p_proxy


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser(description="proxy001 一键注册机")
    ap.add_argument("--count", type=int, default=0, help="注册数量（跳过询问）")
    ap.add_argument("--yes", action="store_true",
                    help="从环境变量读 key，不交互询问")
    ap.add_argument("--solver-base", default=os.environ.get(
        "SOLVER_BASE", DEFAULT_SOLVER_BASE))
    ap.add_argument("--interval", type=float, default=3.0,
                    help="每个账号之间的间隔秒数")
    # 兼容远程一键执行（PowerShell 的 irm|iex 传不进命令行参数）：
    # 若 PROXY001_ARGS 有值且命令行没给参数，就用它补充。
    _extra = os.environ.get("PROXY001_ARGS", "").strip()
    if _extra and len(sys.argv) <= 1:
        sys.argv.extend([x for x in _extra.split() if x])
    args = ap.parse_args()

    title("proxy001 一键注册机  ·  500MB 试用流量")
    log(c("  纯协议实现，无需浏览器。当前流量仅对海外/香港出口可用"
          "（大陆网络会被站点拒绝，错误码 423）。", "gray"))
    log("")

    # ---- 1. key ----
    if args.yes:
        k_mail = os.environ.get("YYDS_KEY", "").strip()
        k_cap = os.environ.get("SOLVER_KEY", "").strip()
        if not k_mail or not k_cap:
            log(c("  --yes 需要环境变量 YYDS_KEY 与 SOLVER_KEY", "red"))
            sys.exit(2)
    else:
        log(c("[1/3] 邮箱服务 key（YYDS Mail）", "bold"))
        log(c("      Base: https://maliapi.215.im/v1", "gray"))
        k_mail = ask("YYDS key", default=os.environ.get("YYDS_KEY") or None,
                     secret=True)
        log("")
        log(c("[2/3] 打码站 key（Turnstile solver）", "bold"))
        log(c("      Base: %s" % args.solver_base, "gray"))
        k_cap = ask("打码 key", default=os.environ.get("SOLVER_KEY") or None,
                    secret=True)
        log("")

    # ---- 2. 连通性自检 ----
    log(c("[*] 自检中...", "gray"))
    try:
        mailer = YYDSMail(k_mail, log=lambda *a: None)
        me = mailer.me()
        q = me.get("quota") or {}
        doms = mailer.domains()
        log("  " + c("✓", "green") + " YYDS 可用  域名 %d 个（verified+MX）  "
            "并发上限 %s" % (len(doms), q.get("maxRps", "?")))
    except Exception as e:
        log("  " + c("✗", "red") + " YYDS 不可用: %s" % str(e)[:140])
        sys.exit(2)

    try:
        solver = CapSolver(args.solver_base, k_cap, log=lambda *a: None)
        bal = solver.balance()
        log("  " + c("✓", "green") + " 打码站可用  余额 %s / %s  "
            "并发 %s" % (bal.get("balance"), bal.get("quota_total"),
                        bal.get("concurrency_limit")))
    except SolverError as e:
        log("  " + c("✗", "red") + " 打码站不可用: %s" % str(e)[:140])
        sys.exit(2)
    except Exception as e:
        log("  " + c("✗", "red") + " 打码站连接失败: %s" % str(e)[:140])
        sys.exit(2)

    # ---- 3. 数量 ----
    if args.count > 0:
        n = args.count
        log("")
        log(c("[3/3] 注册数量: %d（来自 --count）" % n, "bold"))
    else:
        log("")
        log(c("[3/3] 要注册多少个？", "bold"))
        n = ask_int("数量", default=1, lo=1, hi=100)

    sol_bal = int(bal.get("balance") or 0)
    log("")
    log(c("  计划：注册 %d 个，预计消耗打码额度 %d 次（当前余额 %d）"
          % (n, n, sol_bal), "gray"))
    if sol_bal < n:
        log(c("  ⚠ 打码余额可能不足，实际可成功约 %d 个" % sol_bal, "yellow"))
    log(c("  说明：每个账号约 20-40 秒（打码 5-10s + 收信 5-15s + 抓信息）", "gray"))
    log("")
    if not args.yes and not ask_yes("确认开始？", default="y"):
        log(c("  已取消。", "yellow"))
        return

    # ---- 4. 开跑 ----
    log("")
    hr("═")
    log(c("  开始注册", "bold"))
    hr("═")

    solver.log = lambda m: log("  " + c(m, "gray"))
    mailer.log = lambda m: log("  " + c(m, "gray"))

    results = []
    t_start = time.time()
    for i in range(1, n + 1):
        log("")
        log(c("[%d/%d] 处理中..." % (i, n), "bold"))
        rec = None
        try:
            rec = register_one(solver, mailer, log=lambda m: log("  " + c(m, "gray")))
        except SolverError as e:
            log("  " + c("✗ 打码站硬错误，终止：%s" % str(e)[:140], "red"))
            results.append({"ok": False, "error": str(e)[:200],
                            "stage": "solver", "email": None})
            break
        except Exception as e:
            log("  " + c("✗ 异常：%s" % str(e)[:140], "red"))
            log(c(traceback.format_exc()[-600:], "gray"))
            rec = {"ok": False, "error": str(e)[:200], "stage": "exception",
                   "email": None}

        results.append(rec)

        if rec.get("ok"):
            log("  " + c("✓ 成功", "green"))
            log(format_account(i, n, rec))
        else:
            log("  " + c("✗ 失败", "red") + "  %s  (stage=%s)"
                % (rec.get("error"), rec.get("stage")))
            if rec.get("email"):
                log("  邮箱: %s" % rec.get("email"))

        # 每个账号之间留间隔，避免触发站点频控
        if i < n:
            time.sleep(args.interval)

    # ---- 5. 汇总 ----
    ok = [r for r in results if r.get("ok")]
    fail = [r for r in results if not r.get("ok")]
    elapsed = time.time() - t_start

    log("")
    hr("═")
    log(c("  完成", "bold"))
    hr("═")
    log("  成功 " + c(str(len(ok)), "green") + " / 共 " + str(len(results))
        + "    耗时 %.0fs" % elapsed)
    if fail:
        log("  失败 " + c(str(len(fail)), "red"))
        for r in fail:
            log("    - %s  %s" % (r.get("email") or "-", r.get("error")))

    if results:
        meta = {"started_at": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
            "elapsed_s": round(elapsed, 1),
            "requested": n, "ok": len(ok), "failed": len(fail),
            "solver_base": args.solver_base}
        p_json, p_txt, p_proxy = save_outputs(results, meta)
        log("")
        log(c("  结果已保存：", "bold"))
        log("    " + p_json)
        log("    " + p_txt)
        log("    " + p_proxy)
        if ok:
            log("")
            log(c("  ⚠ 试用流量限时（约 6 小时），请尽快领取使用；"
                  "过期后需在后台充值。", "yellow"))
    log("")

    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("")
        log(c("  已中断。", "yellow"))
        sys.exit(130)
