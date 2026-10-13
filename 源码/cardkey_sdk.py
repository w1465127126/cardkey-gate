#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cardkey_sdk.py — 受保护程序用的卡密校验 SDK

用法（3 行接入）：

    import cardkey_sdk
    if not cardkey_sdk.gate(app_id="MY_APP", repo="yourname/keys",
                            raw_url="https://raw.githubusercontent.com/yourname/keys/main/keys.json"):
        raise SystemExit  # 用户没通过，程序直接退出

gate() 会弹出一个输入框让用户填卡密，校验通过后写入本地 license.dat，
之后每次启动先用本地授权（离线也能用），再择机联网复核。

自带 GUI 兜底：如果环境没有 tkinter，会退化成控制台输入。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardkey_store as cs  # noqa: E402

__all__ = ["gate", "verify_key", "machine_id", "GateConfig"]

# 全局配置（打包时会被 build 脚本改写成你的仓库地址）
CONFIG = {
    "repo": "",
    "path": cs.DEFAULT_PATH,
    "branch": cs.DEFAULT_BRANCH,
    "raw_url": "",
    "app_id": cs.DEFAULT_APP_ID,
    "app_title": "",
    "secret": "",
    "token": "",
    "offline_grace_days": 30,   # 本地授权多久后必须联网复核
    "allow_offline": True,
}


class GateConfig(dict):
    """顺手点：with GateConfig(repo=...) as c: ..."""
    def __init__(self, **kw):
        super().__init__(CONFIG)
        self.update({k: v for k, v in kw.items() if v is not None})

    def __enter__(self):
        CONFIG.update(self)
        return self

    def __exit__(self, *a):
        return False


# --------------------------------------------------------------------------
# 底层：拉库 + 校验
# --------------------------------------------------------------------------

def _store() -> cs.GitHubStore:
    return cs.GitHubStore(
        repo=CONFIG.get("repo", ""),
        path=CONFIG.get("path", cs.DEFAULT_PATH),
        branch=CONFIG.get("branch", cs.DEFAULT_BRANCH),
        token=CONFIG.get("token", ""),
        raw_url=CONFIG.get("raw_url", ""),
    )


def fetch_store(prefer_api: bool = True) -> dict:
    """从 GitHub 拉卡密库。异常时抛出，调用方决定是否走离线。"""
    return _store().read(prefer_api=prefer_api)[0]


def verify_key(key: str, app_id: str = "", machine: str = "", store: dict | None = None,
               net: bool = True) -> dict:
    """校验一张卡密，返回 {ok, code, reason, record}。"""
    app_id = app_id or CONFIG.get("app_id", cs.DEFAULT_APP_ID)
    machine = machine or cs.machine_id()
    st = store
    if st is None:
        if not net:
            return {"ok": False, "code": "OFFLINE", "reason": cs.REASON_TEXT["OFFLINE"],
                    "record": None, "app": None}
        try:
            st = fetch_store()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "code": "STORE_ERROR",
                    "reason": f"{cs.REASON_TEXT['STORE_ERROR']}：{e}", "record": None, "app": None}
    return cs.verify(st, app_id, key, machine=machine, secret=CONFIG.get("secret", ""))


# --------------------------------------------------------------------------
# 输入界面
# --------------------------------------------------------------------------

def _ask_gui(title: str, hint: str, prefill: str = "") -> str | None:
    """弹输入框，返回卡密或 None（取消）。"""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return _ask_console(hint)

    result = {"val": None}
    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    frm = ttk.Frame(root, padding=18)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=hint or "请输入卡密：", font=("Microsoft YaHei UI", 10)).pack(anchor="w")
    var = tk.StringVar(value=prefill)
    ent = ttk.Entry(frm, textvariable=var, width=34, font=("Consolas", 12))
    ent.pack(fill="x", pady=(8, 4))
    ent.focus_set()

    msg = ttk.Label(frm, text="", foreground="#c0392b", wraplength=280)
    msg.pack(anchor="w")
    ttk.Label(frm, text=f"机器码：{cs.pretty_machine(cs.machine_id())}",
              foreground="#7f8c8d").pack(anchor="w", pady=(2, 10))

    def ok(*_):
        v = var.get().strip()
        if not v:
            msg.config(text="卡密不能为空")
            return
        result["val"] = v
        root.destroy()

    bar = ttk.Frame(frm)
    bar.pack(fill="x")
    ttk.Button(bar, text="确定", command=ok).pack(side="right")
    ttk.Button(bar, text="取消", command=root.destroy).pack(side="right", padx=6)
    root.bind("<Return>", ok)
    root.bind("<Escape>", lambda *_: root.destroy())
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry(f"+{x}+{y}")
    root.mainloop()
    return result["val"]


def _ask_console(hint: str) -> str | None:
    try:
        v = input(f"{hint or '请输入卡密'}：").strip()
        return v or None
    except (EOFError, KeyboardInterrupt):
        return None


def _toast_ok(title: str, text: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        messagebox.showinfo(title, text)
        r.destroy()
    except Exception:
        print(f"[{title}] {text}")


def _toast_err(title: str, text: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        messagebox.showerror(title, text)
        r.destroy()
    except Exception:
        print(f"[{title}] {text}", file=sys.stderr)


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def gate(app_id: str = "", repo: str = "", raw_url: str = "", path: str = "",
         branch: str = "", secret: str = "", title: str = "",
         force_prompt: bool = False, max_tries: int = 5,
         offline_grace_days: int | None = None, cache_path: str = "") -> bool:
    """卡密门禁。返回 True 表示放行。

    流程：
      1. 本地 license.dat 有效 且 未超过复核周期 -> 直接放行（可选联网复核）
      2. 否则弹输入框，联网校验卡密
      3. 通过 -> 写 license.dat -> 放行
    """
    if app_id:
        CONFIG["app_id"] = app_id
    if repo:
        CONFIG["repo"] = repo
    if raw_url:
        CONFIG["raw_url"] = raw_url
    if path:
        CONFIG["path"] = path
    if branch:
        CONFIG["branch"] = branch
    if secret is not None and secret != "":
        CONFIG["secret"] = secret
    if offline_grace_days is not None:
        CONFIG["offline_grace_days"] = offline_grace_days

    app_id = CONFIG.get("app_id", cs.DEFAULT_APP_ID)
    title = title or CONFIG.get("app_title") or "软件授权验证"
    machine = cs.machine_id()
    lp = cache_path or cs.default_license_path()

    # ---- 1. 本地授权 ----
    lic = cs.load_license(lp)
    if lic and not force_prompt and cs.check_license(lic, app_id, machine):
        issued = lic.get("issued", "")
        age_days = 9999
        try:
            age_days = (time.time() - time.mktime(time.strptime(issued, "%Y-%m-%dT%H:%M:%SZ"))) / 86400
        except Exception:
            pass
        if age_days <= CONFIG.get("offline_grace_days", 30):
            # 有网时顺手复核一次；拉不到库就按离线继续
            try:
                r = verify_key(lic.get("key", ""), app_id, machine)
                if r.get("ok"):
                    return True
                if r.get("code") in ("REVOKED", "EXPIRED", "EXHAUSTED", "MACHINE_MISMATCH"):
                    _toast_err(title, f"授权已失效：{r['reason']}\n\n请重新输入卡密。")
                    os.remove(lp) if os.path.exists(lp) else None
                    lic = None
                else:
                    return True
            except Exception:
                return True  # 网络问题不打断老用户

    # ---- 2. 弹框 + 联网校验 ----
    tries = 0
    while tries < max_tries:
        tries += 1
        key = _ask_gui(title, "请输入卡密（形如 XXXX-XXXX-XXXX-XXXX）：")
        if not key:
            return False

        r = verify_key(key, app_id, machine)
        if r.get("ok"):
            cs.save_license(cs.make_license(app_id, key, machine), lp)
            _toast_ok(title, "验证成功，欢迎使用！")
            return True

        if r.get("code") == "STORE_ERROR":
            # 拉库失败：本地没有有效授权才拦
            ok = False
            if CONFIG.get("allow_offline") and lic and cs.check_license(lic, app_id, machine):
                _toast_ok(title, "网络不可用，使用本地授权进入。")
                ok = True
            if ok:
                return True
            _toast_err(title, f"{r['reason']}\n\n请检查网络后重试。")
            continue

        _toast_err(title, f"验证失败：{r['reason']}（还可尝试 {max_tries - tries} 次）")

    return False


# --------------------------------------------------------------------------
# 命令行：给 bat/快捷方式调用
# --------------------------------------------------------------------------

def _cli():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="卡密校验")
    ap.add_argument("--app-id", default="")
    ap.add_argument("--repo", default="")
    ap.add_argument("--raw-url", default="")
    ap.add_argument("--secret", default="")
    ap.add_argument("--machine", action="store_true", help="只打印本机机器码后退出")
    ap.add_argument("--check", default="", help="不弹框，直接校验指定卡密，打印 JSON")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()

    if a.machine:
        mid = cs.machine_id()
        if a.json:
            print(json.dumps({"machine_id": mid, "pretty": cs.pretty_machine(mid)}, ensure_ascii=False))
        else:
            print(cs.pretty_machine(mid))
        return 0

    if a.check:
        r = verify_key(a.check, a.app_id, store=None)
        out = {"ok": r.get("ok"), "code": r.get("code"), "reason": r.get("reason")}
        if a.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            print(("PASS" if out["ok"] else "FAIL") + " " + str(out["reason"]))
        return 0 if out["ok"] else 1

    ok = gate(app_id=a.app_id, repo=a.repo, raw_url=a.raw_url, secret=a.secret)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_cli())
