#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
keygen_gui.py — 卡密管理端（你自己的工具，不发给别人）

功能：
  1. 在程序内创建卡密（批量、设有效期/次数/绑定机器/备注）
  2. 一键推送到 GitHub 仓库
  3. 列表查看状态（未使用/已激活/已过期/已吊销）、吊销、删除
  4. 记录 APP_ID，直接复制给受保护程序用

打包：  build.bat   （产出 dist\\CardKeyManager.exe）

配置写在 build 时注入的 app_config.json 里，也可以直接在界面顶部改。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardkey_store as cs  # noqa: E402

# --------------------------------------------------------------------------
# 配置加载
# --------------------------------------------------------------------------

def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def load_config() -> dict:
    cfg = {
        "repo": "",              # owner/repo
        "path": cs.DEFAULT_PATH,  # 仓库内文件路径
        "branch": cs.DEFAULT_BRANCH,
        "token": "",
        "secret": "",
        "app_id": cs.DEFAULT_APP_ID,
        "app_name": "",
    }
    for p in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_config.json"),
              resource_path("app_config.json"),
              os.path.join(os.path.expanduser("~"), ".cardkey-gate", "config.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if v not in (None, "")})
            break
        except Exception:
            continue
    return cfg


def save_config(cfg: dict) -> str:
    """配置存到用户目录，避免打包后写不进程序目录。"""
    d = os.path.join(os.path.expanduser("~"), ".cardkey-gate")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return p


# --------------------------------------------------------------------------
# 主界面
# --------------------------------------------------------------------------

class Manager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("卡密管理端 · CardKeyManager")
        self.geometry("1080x720")
        self.minsize(940, 620)

        self.cfg = load_config()
        self.store: dict = cs.empty_store()
        self.sha: str | None = None
        self.dirty = False

        self._build_style()
        self._build_ui()
        self.after(300, self.on_test_conn)

    # ---------------- 样式 ----------------
    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TButton", padding=6)
        st.configure("Accent.TButton", padding=6)
        st.configure("Treeview", rowheight=24)
        st.configure("TLabel", padding=(2, 2))

    # ---------------- 布局 ----------------
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # === 仓库配置 ===
        top = ttk.LabelFrame(root, text="① 仓库配置（GitHub 作为卡密库）", padding=8)
        top.pack(fill="x")

        g = ttk.Frame(top)
        g.pack(fill="x")
        self.var_repo = tk.StringVar(value=self.cfg.get("repo", ""))
        self.var_path = tk.StringVar(value=self.cfg.get("path", cs.DEFAULT_PATH))
        self.var_branch = tk.StringVar(value=self.cfg.get("branch", cs.DEFAULT_BRANCH))
        self.var_token = tk.StringVar(value=self.cfg.get("token", ""))
        self.var_secret = tk.StringVar(value=self.cfg.get("secret", ""))

        def row(parent, label, var, width=28, show=None, r=0, c=0, tip=""):
            ttk.Label(parent, text=label).grid(row=r, column=c * 2, sticky="e", padx=(0, 4), pady=3)
            e = ttk.Entry(parent, textvariable=var, width=width, show=show)
            e.grid(row=r, column=c * 2 + 1, sticky="we", padx=(0, 14), pady=3)
            return e

        row(g, "仓库 owner/repo", self.var_repo, 30, r=0, c=0)
        row(g, "文件路径", self.var_path, 18, r=0, c=1)
        row(g, "分支", self.var_branch, 12, r=1, c=0)
        row(g, "PAT Token（写权限）", self.var_token, 30, show="*", r=1, c=1)
        row(g, "HMAC secret（可空）", self.var_secret, 18, show="*", r=2, c=0)
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)

        btns = ttk.Frame(top)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="测试连接", command=self.on_test_conn).pack(side="left")
        ttk.Button(btns, text="从仓库拉取", command=self.on_pull).pack(side="left", padx=6)
        ttk.Button(btns, text="保存配置到本机", command=self.on_save_cfg).pack(side="left")
        ttk.Button(btns, text="初始化空卡密库(本地)", command=self.on_new_store).pack(side="left", padx=6)
        self.lbl_conn = ttk.Label(btns, text="未连接")
        self.lbl_conn.pack(side="right")

        # === 生成卡密 ===
        mid = ttk.LabelFrame(root, text="② 生成卡密", padding=8)
        mid.pack(fill="x", pady=(10, 0))

        m = ttk.Frame(mid)
        m.pack(fill="x")
        self.var_appid = tk.StringVar(value=self.cfg.get("app_id", cs.DEFAULT_APP_ID))
        self.var_appname = tk.StringVar(value=self.cfg.get("app_name", ""))
        self.var_note = tk.StringVar(value="")
        self.var_days = tk.StringVar(value="0")
        self.var_uses = tk.StringVar(value="1")
        self.var_count = tk.StringVar(value="10")
        self.var_bind = tk.StringVar(value="")
        self.var_person = tk.BooleanVar(value=False)

        row(m, "APP_ID", self.var_appid, 20, r=0, c=0)
        row(m, "显示名", self.var_appname, 16, r=0, c=1)
        row(m, "备注", self.var_note, 20, r=0, c=2)
        row(m, "有效期(天, 0=永久)", self.var_days, 8, r=1, c=0)
        row(m, "次数(0=不限)", self.var_uses, 8, r=1, c=1)
        row(m, "生成数量", self.var_count, 8, r=1, c=2)
        row(m, "绑定机器码(空=不绑)", self.var_bind, 20, r=2, c=0)
        ttk.Checkbutton(m, text="首次使用自动绑定机器", variable=self.var_person).grid(
            row=2, column=2, sticky="w", padx=(0, 10))
        m.columnconfigure(1, weight=1)
        m.columnconfigure(3, weight=1)
        m.columnconfigure(5, weight=1)

        mb = ttk.Frame(mid)
        mb.pack(fill="x", pady=(6, 0))
        ttk.Button(mb, text="生成卡密", style="Accent.TButton", command=self.on_generate).pack(side="left")
        ttk.Button(mb, text="复制本次生成的卡密", command=self.on_copy_generated).pack(side="left", padx=6)
        ttk.Button(mb, text="推送仓库", command=self.on_push).pack(side="left")
        ttk.Button(mb, text="导出 TXT", command=self.on_export).pack(side="left", padx=6)
        self.var_generated: list[str] = []

        # === 卡密列表 ===
        bot = ttk.LabelFrame(root, text="③ 卡密列表", padding=8)
        bot.pack(fill="both", expand=True, pady=(10, 0))

        cols = ("key", "app", "note", "status", "uses", "expire", "machine", "created", "last_used")
        heads = ("卡密", "APP_ID", "备注", "状态", "次数", "有效期至", "绑定机器", "创建时间", "最后使用")
        widths = (150, 90, 130, 70, 60, 130, 130, 130, 130)
        self.tree = ttk.Treeview(bot, columns=cols, show="headings", selectmode="extended")
        for c_, h_, w_ in zip(cols, heads, widths):
            self.tree.heading(c_, text=h_)
            self.tree.column(c_, width=w_, anchor="center")
        vs = ttk.Scrollbar(bot, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self.tree.tag_configure("used", foreground="#1f6feb")
        self.tree.tag_configure("dead", foreground="#a0a0a0")

        tb = ttk.Frame(bot)
        tb.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(tb, text="刷新列表", command=self.refresh_tree).pack(fill="x", pady=2)
        ttk.Button(tb, text="复制选中卡密", command=self.on_copy_selected).pack(fill="x", pady=2)
        ttk.Button(tb, text="吊销选中", command=lambda: self.on_revoke(True)).pack(fill="x", pady=2)
        ttk.Button(tb, text="恢复选中", command=lambda: self.on_revoke(False)).pack(fill="x", pady=2)
        ttk.Button(tb, text="删除选中", command=self.on_delete).pack(fill="x", pady=2)
        ttk.Button(tb, text="我的机器码", command=self.on_show_machine).pack(fill="x", pady=(14, 2))

        # === 状态栏 ===
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.var_status, anchor="w").pack(fill="x", pady=(6, 0))

    # ---------------- 工具 ----------------
    def gh(self) -> cs.GitHubStore:
        return cs.GitHubStore(
            repo=self.var_repo.get().strip(),
            path=self.var_path.get().strip() or cs.DEFAULT_PATH,
            branch=self.var_branch.get().strip() or cs.DEFAULT_BRANCH,
            token=self.var_token.get().strip(),
        )

    def status(self, msg: str):
        """更新时间戳状态栏。后台线程调用时会自动转回主线程。"""
        def apply():
            self.var_status.set(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if threading.current_thread() is threading.main_thread():
            apply()
            try:
                self.update_idletasks()
            except Exception:
                pass
        else:
            try:
                self.after(0, apply)
            except Exception:
                pass

    def bg(self, fn, *a, **kw):
        """把网络操作丢后台，避免界面假死。"""
        def run():
            try:
                fn(*a, **kw)
            except Exception as e:  # noqa: BLE001
                # 注意：except 里的 e 在块结束时会被删除，必须用默认参数绑死
                self.after(0, lambda err=str(e): messagebox.showerror("出错", err))
                self.after(0, lambda err=str(e): self.status("失败：" + err))
        threading.Thread(target=run, daemon=True).start()

    # ---------------- 事件 ----------------
    def on_save_cfg(self):
        cfg = {
            "repo": self.var_repo.get().strip(),
            "path": self.var_path.get().strip(),
            "branch": self.var_branch.get().strip(),
            "token": self.var_token.get().strip(),
            "secret": self.var_secret.get().strip(),
            "app_id": self.var_appid.get().strip(),
            "app_name": self.var_appname.get().strip(),
        }
        p = save_config(cfg)
        self.status(f"配置已保存到 {p}")

    def on_test_conn(self):
        def work():
            self.after(0, lambda: self.status("正在连接仓库…"))
            try:
                store, sha = self.gh().read(prefer_api=True)
                self.store, self.sha = store, sha
                n = sum(len(a.get("keys") or {}) for a in (store.get("apps") or {}).values())
                apps = ", ".join((store.get("apps") or {}).keys()) or "（空）"
                txt = f"✅ 已连接  sha={str(sha)[:7]}  卡密 {n} 张  应用: {apps}"
                self.after(0, lambda t=txt: self.lbl_conn.config(text=t))
                self.after(0, lambda: self.status("仓库读取成功"))
                self.after(0, self.refresh_tree)
            except Exception as e:  # noqa: BLE001
                msg = (f"连接失败：{e}（可先点『初始化空卡密库』本地用，"
                       f"配好仓库再推送）")
                self.after(0, lambda: self.lbl_conn.config(text="❌ 连接失败"))
                self.after(0, lambda m=msg: self.status(m))
        self.bg(work)

    def on_pull(self):
        def work():
            self.after(0, lambda: self.status("拉取仓库…"))
            s, sha = self.gh().read(prefer_api=True)
            self.store, self.sha, self.dirty = s, sha, False
            self.after(0, self.refresh_tree)
            self.after(0, lambda t=f"已拉取，sha={str(sha)[:7]}": self.status(t))
        self.bg(work)

    def on_new_store(self):
        if self.dirty and not messagebox.askyesno("确认", "当前有未推送的改动，确定覆盖为空白卡密库？"):
            return
        self.store = cs.empty_store(note="created by CardKeyManager")
        self.sha = None
        self.dirty = True
        self.refresh_tree()
        self.status("已初始化空白卡密库（记得推送仓库）")

    def on_generate(self):
        try:
            days = int(self.var_days.get() or 0)
            uses = int(self.var_uses.get() or 0)
            count = max(1, min(2000, int(self.var_count.get() or 1)))
        except ValueError:
            messagebox.showerror("参数错误", "有效期/次数/数量必须是整数")
            return
        app_id = self.var_appid.get().strip() or cs.DEFAULT_APP_ID
        keys = cs.add_key(
            self.store, app_id,
            note=self.var_note.get().strip(),
            days=days, max_uses=uses,
            bind_machine=self.var_bind.get().strip(),
            bind_on_first_use=bool(self.var_person.get()),
            count=count,
            app_name=self.var_appname.get().strip(),
        )
        self.var_generated = keys
        self.dirty = True
        self.refresh_tree()
        self.status(f"已生成 {len(keys)} 张卡密（APP_ID={app_id}），点『推送仓库』生效")

    def on_copy_generated(self):
        if not self.var_generated:
            messagebox.showinfo("提示", "本次还没有生成卡密")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.var_generated))
        self.status(f"已复制 {len(self.var_generated)} 张卡密到剪贴板")

    def on_export(self):
        if not self.var_generated:
            messagebox.showinfo("提示", "本次还没有生成卡密")
            return
        p = os.path.join(os.path.expanduser("~"), "Desktop",
                         f"keys_{time.strftime('%Y%m%d_%H%M%S')}.txt")
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# APP_ID={self.var_appid.get().strip()}\n")
                f.write(f"# 生成时间={cs.now_iso()}\n")
                for k in self.var_generated:
                    f.write(k + "\n")
            self.status(f"已导出 {p}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导出失败", str(e))

    def on_push(self):
        if not self.var_token.get().strip():
            messagebox.showerror("缺少 Token", "写回仓库需要 PAT Token（classic 勾 repo / fine-grained 勾 Contents: RW）")
            return

        def work():
            self.after(0, lambda: self.status("推送中…"))
            sha = self.gh().write(
                self.store, message=f"update keys ({len(self.var_generated)} new)",
                sha=self.sha, secret=self.var_secret.get().strip())
            self.sha, self.dirty = sha, False
            self.after(0, lambda t=f"✅ 推送成功 sha={sha[:7]}": self.status(t))
            self.after(0, lambda: self.lbl_conn.config(text="✅ 已同步"))
        self.bg(work)

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        rows = list(cs.iter_keys(self.store))
        rows.sort(key=lambda r: (r[2].get("created") or ""), reverse=True)
        for aid, nk, rec in rows:
            st = cs.key_status(rec)
            tag = "dead" if st in ("已吊销", "已过期", "已用尽") else ("used" if st == "已激活" else "")
            self.tree.insert("", "end", values=(
                rec.get("key") or cs.pretty_key(nk), aid, rec.get("note", ""), st,
                f"{rec.get('uses', 0)}/{rec.get('max_uses', 0) or '∞'}",
                rec.get("expire") or "永久",
                rec.get("machine") or rec.get("bind_machine") or "-",
                rec.get("created", ""), rec.get("last_used", "") or "-",
            ), tags=(tag,) if tag else ())

    def _selected_keys(self):
        out = []
        for iid in self.tree.selection():
            v = self.tree.item(iid, "values")
            out.append((v[1], v[0]))
        return out

    def on_copy_selected(self):
        sel = self._selected_keys()
        if not sel:
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(k for _, k in sel))
        self.status(f"已复制 {len(sel)} 张")

    def on_revoke(self, on: bool):
        n = 0
        for aid, k in self._selected_keys():
            n += 1 if cs.revoke_key(self.store, aid, k, on) else 0
        if n:
            self.dirty = True
            self.refresh_tree()
            self.status(f"{'吊销' if on else '恢复'} {n} 张，记得推送仓库")

    def on_delete(self):
        sel = self._selected_keys()
        if not sel or not messagebox.askyesno("确认", f"删除 {len(sel)} 张卡密？"):
            return
        for aid, k in sel:
            cs.delete_key(self.store, aid, k)
        self.dirty = True
        self.refresh_tree()
        self.status(f"已删除 {len(sel)} 张，记得推送仓库")

    def on_show_machine(self):
        mid = cs.machine_id()
        pretty = cs.pretty_machine(mid)
        self.clipboard_clear()
        self.clipboard_append(pretty)
        messagebox.showinfo("本机机器码", f"{pretty}\n\n已复制到剪贴板。\n把它填进『绑定机器码』就能限定只能这台机用。")


def main():
    app = Manager()
    app.mainloop()


if __name__ == "__main__":
    main()
