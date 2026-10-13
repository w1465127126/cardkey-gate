#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_protected_app.py — 示例：一个被卡密保护的程序

运行后会先弹卡密框，验证通过才显示主界面。
把你的私货代码写在 main_window() 里即可。

用法：
    python demo_protected_app.py
    python demo_protected_app.py --check XXXX-XXXX-XXXX-XXXX   # 命令行校验
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardkey_sdk as sdk  # noqa: E402

# ==========================================================================
# >>> 改这里：你的仓库地址和 APP_ID <<<
# ==========================================================================
REPO = "w1465127126/cardkey-gate"
RAW_URL = "https://raw.githubusercontent.com/w1465127126/cardkey-gate/main/keys.json"
APP_ID = "DEMO_APP"
APP_TITLE = "示例受保护程序"


def _local_secret() -> str:
    """从本地配置读 HMAC secret —— 绝不写进源码、绝不进仓库。

    公开仓库里的 keys.json 带 sig，客户端要校验签名得先拿到 secret；
    secret 放在 %USERPROFILE%\\.cardkey-gate\\config.json（已被 .gitignore 排除）。
    读不到就返回空串，此时 SDK 退化为「不校验签名」，明文库照样能跑。
    """
    p = os.path.join(os.path.expanduser("~"), ".cardkey-gate", "config.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return str(json.load(f).get("secret") or "")
    except Exception:
        return ""
# ==========================================================================


def main_window():
    """验证通过后展示的界面 —— 换成你自己的程序。"""
    root = tk.Tk()
    root.title(f"{APP_TITLE} · 已授权")
    root.geometry("560x340")

    frm = ttk.Frame(root, padding=22)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="✅ 授权通过", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
    ttk.Label(frm, text=f"APP_ID：{APP_ID}", foreground="#555").pack(anchor="w", pady=(6, 0))
    ttk.Label(frm, text=f"机器码：{sdk.cs.pretty_machine(sdk.cs.machine_id())}",
              foreground="#555").pack(anchor="w")

    ttk.Separator(frm).pack(fill="x", pady=12)
    ttk.Label(frm, text="↓ 这里放你自己的功能界面 ↓",
              font=("Microsoft YaHei UI", 11)).pack(anchor="w")
    ttk.Label(frm, text="（主界面代码写在 demo_protected_app.py 的 main_window() 里）",
              foreground="#888").pack(anchor="w", pady=(4, 0))
    ttk.Button(frm, text="关闭", command=root.destroy).pack(side="bottom", anchor="e")
    root.mainloop()


def main():
    ok = sdk.gate(
        app_id=APP_ID,
        repo=REPO,
        raw_url=RAW_URL,
        secret=_local_secret(),
        title=f"{APP_TITLE} · 授权验证",
        # 测试阶段没有真仓库时，把下面这行改成 True 会每次都弹框
        force_prompt="--force" in sys.argv,
    )
    if not ok:
        print("未通过授权验证，程序退出。", file=sys.stderr)
        return 1
    main_window()
    return 0


if __name__ == "__main__":
    sys.exit(main())
