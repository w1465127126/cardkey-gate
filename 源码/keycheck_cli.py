#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
keycheck_cli.py — 控制台校验器（给 .bat / 快捷方式 / 批处理调用）

用法：
    KeyCheck.exe --check XXXX-XXXX-XXXX-XXXX     校验卡密，通过 exit 0，失败 exit 1
    KeyCheck.exe --machine                       打印本机机器码
    KeyCheck.exe                                 弹窗输入卡密

在 .bat 里锁住自己的程序：

    @echo off
    KeyCheck.exe --check %1 || (echo 卡密无效 & pause & exit /b 1)
    start "" MyRealApp.exe

配置文件 keycheck.json（与 exe 同目录，或 %USERPROFILE%\\.cardkey-gate\\config.json）：
{
  "repo": "owner/repo",
  "path": "keys.json",
  "branch": "main",
  "raw_url": "",
  "app_id": "MY_APP",
  "secret": ""
}
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，中文会乱码 —— 强制 UTF-8
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import cardkey_sdk as sdk  # noqa: E402
import cardkey_store as cs  # noqa: E402


def find_config() -> dict:
    cands = [
        os.path.join(os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)), "keycheck.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "keycheck.json"),
        os.path.join(os.path.expanduser("~"), ".cardkey-gate", "config.json"),
    ]
    for p in cands:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return {k: v for k, v in json.load(f).items() if v not in (None, "")}
        except Exception:
            continue
    return {}


def main():
    cfg = find_config()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check", default="", help="直接校验，不弹框")
    ap.add_argument("--machine", action="store_true", help="打印机器码")
    ap.add_argument("--app-id", default=cfg.get("app_id", ""))
    ap.add_argument("--repo", default=cfg.get("repo", ""))
    ap.add_argument("--raw-url", default=cfg.get("raw_url", ""))
    ap.add_argument("--secret", default=cfg.get("secret", ""))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    for k, v in (("app_id", a.app_id), ("repo", a.repo), ("raw_url", a.raw_url), ("secret", a.secret)):
        if v:
            sdk.CONFIG[k] = v

    if a.machine:
        mid = cs.machine_id()
        print(json.dumps({"machine_id": mid, "pretty": cs.pretty_machine(mid)}, ensure_ascii=False)
              if a.json else cs.pretty_machine(mid))
        return 0

    if a.check:
        r = sdk.verify_key(a.check)
        if a.json:
            print(json.dumps({"ok": r.get("ok"), "code": r.get("code"), "reason": r.get("reason")},
                             ensure_ascii=False))
        else:
            print(("PASS" if r.get("ok") else "FAIL") + " " + str(r.get("reason")))
        return 0 if r.get("ok") else 1

    print("机器码：" + cs.pretty_machine(cs.machine_id()))
    ok = sdk.gate()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
