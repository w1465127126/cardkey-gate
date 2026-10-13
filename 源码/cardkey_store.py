#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cardkey_store.py — 卡密库核心模块

数据源：GitHub 仓库内的一个 JSON 文件（默认为 keys.json）。
读取走 GitHub Contents API（绕开 CDN 缓存，吊销能立刻生效），失败时回落到
raw.githubusercontent.com 并带 cache-bust 参数。

按需求方要求，本方案不做强安全设计：卡密库是明文 JSON，客户端内置仓库地址。
如需稍强一点，可开启 secret + sign（HMAC-SHA256），见 sign_store() / verify()。

作者备注：核心逻辑完全离网可测（不依赖第三方库），仅用标准库。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import ssl
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# 去掉 0/O/1/I/L/S/5/B/8/2/Z 这些容易看错的字符，剩 28 个
KEY_CHARSET = "ACDEFGHJKMNPQRTUVWXY34679"

DEFAULT_BRANCH = "main"
DEFAULT_PATH = "keys.json"
DEFAULT_APP_ID = "APP_ID"
USER_AGENT = "cardkey-gate/1.0 (+local)"

GITHUB_API = "https://api.github.com"
RAW_HOST = "https://raw.githubusercontent.com"

# 校验结果码 -> 中文说明
REASON_TEXT = {
    "OK": "验证通过",
    "APP_NOT_FOUND": "卡密库中找不到这个应用 ID",
    "KEY_NOT_FOUND": "卡密不存在或输入有误",
    "REVOKED": "该卡密已被吊销",
    "EXPIRED": "该卡密已过期",
    "EXHAUSTED": "该卡密可用次数已用尽",
    "NOT_YET_VALID": "该卡密尚未到生效时间",
    "MACHINE_MISMATCH": "该卡密已绑定其它机器",
    "STORE_ERROR": "无法读取卡密库（网络或仓库配置问题）",
    "OFFLINE": "离线状态且无有效本地授权",
    "SIG_INVALID": "卡密库签名校验失败",
    "BAD_INPUT": "请填写卡密",
}


# --------------------------------------------------------------------------
# 卡密生成 / 规范化
# --------------------------------------------------------------------------

def gen_key(groups: int = 4, size: int = 4, charset: str = KEY_CHARSET) -> str:
    """生成形如 ABCD-EFGH-JKLM-NPQR 的卡密。"""
    rng = random.SystemRandom()
    parts = ["".join(rng.choice(charset) for _ in range(size)) for _ in range(groups)]
    return "-".join(parts)


def norm_key(s: str) -> str:
    """标准化：只保留 A-Z0-9 并大写，兼容用户输错分隔符/小写。"""
    return re.sub(r"[^A-Za-z0-9]", "", s or "").upper()


def pretty_key(norm: str, groups: int = 4, size: int = 4) -> str:
    """把规范化后的卡密还原成带连字符的样式。"""
    n = norm_key(norm)
    if len(n) != groups * size:
        return n
    return "-".join(n[i:i + size] for i in range(0, len(n), size))


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso(s) -> float | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------
# 空库 / 序列化
# --------------------------------------------------------------------------

def empty_store(note: str = "") -> dict:
    return {
        "version": 1,
        "updated": now_iso(),
        "note": note,
        "apps": {},
    }


def dump_store(store: dict, pretty: bool = True) -> str:
    store = dict(store)
    store["updated"] = now_iso()
    if pretty:
        return json.dumps(store, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    return json.dumps(store, ensure_ascii=False, separators=(",", ":"))


def load_store_text(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or "apps" not in data:
        raise ValueError("卡密库格式不正确：缺少 apps 字段")
    data.setdefault("version", 1)
    data.setdefault("updated", now_iso())
    for app_id, app in (data.get("apps") or {}).items():
        app.setdefault("name", app_id)
        app.setdefault("keys", {})
    return data


# --------------------------------------------------------------------------
# 增删改
# --------------------------------------------------------------------------

def ensure_app(store: dict, app_id: str, name: str = "") -> dict:
    app_id = (app_id or DEFAULT_APP_ID).strip()
    apps = store.setdefault("apps", {})
    app = apps.setdefault(app_id, {"name": name or app_id, "keys": {}})
    if name:
        app["name"] = name
    app.setdefault("keys", {})
    return app


def add_key(
    store: dict,
    app_id: str,
    note: str = "",
    days: int = 0,
    max_uses: int = 1,
    bind_machine: str = "",
    bind_on_first_use: bool = False,
    count: int = 1,
    app_name: str = "",
) -> list[str]:
    """往库里加卡密，返回本次生成的卡密列表（带连字符样式）。

    days = 0           -> 永久
    max_uses = 0       -> 不限次数
    bind_machine = ""  -> 不绑机器（绑机器表示只有这台机器能用）
    """
    app = ensure_app(store, app_id, app_name)
    created: list[str] = []

    expire = None
    if days and days > 0:
        expire = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + days * 86400)
        )

    for _ in range(max(1, int(count))):
        while True:
            k = gen_key()
            nk = norm_key(k)
            if nk not in app["keys"]:
                break
        app["keys"][nk] = {
            "key": k,
            "note": note,
            "created": now_iso(),
            "expire": expire,
            "max_uses": int(max_uses),
            "uses": 0,
            "bind_machine": (bind_machine or "").strip().upper().replace("-", ""),
            "bind_on_first_use": bool(bind_on_first_use),
            "machine": "",
            "revoked": False,
            "last_used": "",
        }
        created.append(k)

    store["updated"] = now_iso()
    return created


def get_record(store: dict, app_id: str, key: str) -> dict | None:
    app = (store.get("apps") or {}).get(app_id)
    if not app:
        return None
    return (app.get("keys") or {}).get(norm_key(key))


def revoke_key(store: dict, app_id: str, key: str, on: bool = True) -> bool:
    rec = get_record(store, app_id, key)
    if not rec:
        return False
    rec["revoked"] = bool(on)
    store["updated"] = now_iso()
    return True


def delete_key(store: dict, app_id: str, key: str) -> bool:
    app = (store.get("apps") or {}).get(app_id)
    if not app:
        return False
    return app.get("keys", {}).pop(norm_key(key), None) is not None


def iter_keys(store: dict, app_id: str | None = None):
    """产出 (app_id, norm_key, record) 三元组。"""
    for aid, app in (store.get("apps") or {}).items():
        if app_id and aid != app_id:
            continue
        for nk, rec in (app.get("keys") or {}).items():
            yield aid, nk, rec


def key_status(rec: dict, now: float | None = None) -> str:
    """给管理端显示用的状态字样。"""
    now = now or time.time()
    if rec.get("revoked"):
        return "已吊销"
    exp = _parse_iso(rec.get("expire"))
    if exp and now > exp:
        return "已过期"
    mu = int(rec.get("max_uses") or 0)
    if mu and int(rec.get("uses") or 0) >= mu:
        return "已用尽"
    if rec.get("machine"):
        return "已激活"
    return "未使用"


# --------------------------------------------------------------------------
# 签名（可选，默认关闭）
# --------------------------------------------------------------------------

def _canonical(store: dict) -> bytes:
    body = {"apps": store.get("apps") or {}}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_sig(store: dict, secret: str) -> str:
    """算出卡密库的 HMAC-SHA256 签名（纯函数，不改动 store）。"""
    return hmac.new(secret.encode("utf-8"), _canonical(store), hashlib.sha256).hexdigest()


def sign_store(store: dict, secret: str) -> str:
    """给卡密库签名，写入 store["sig"]，返回签名值。"""
    sig = compute_sig(store, secret)
    store["sig"] = sig
    return sig


def check_sig(store: dict, secret: str, require: bool = True) -> bool:
    """校验卡密库签名。

    secret 为空      -> 不校验，返回 True（保持明文模式可用）。
    secret 非空      -> 必须带 sig 且完全匹配，否则返回 False。
                        漏掉这一步就等于没开签名：攻击者只要把 sig 字段
                        删掉就能绕过，所以默认 require=True 强制要求签名存在。
    require=False    -> 只在库自带 sig 时才比对（过渡期用，不推荐）。
    """
    if not secret:
        return True
    stored = store.get("sig")
    if not stored:
        return not require
    return hmac.compare_digest(str(stored), compute_sig(store, secret))


# --------------------------------------------------------------------------
# 机器码
# --------------------------------------------------------------------------

def machine_id() -> str:
    """机器码：卷序列号 + 网卡 + 系统 MachineGuid 的哈希前 16 位。"""
    parts: list[str] = []

    if os.name == "nt":
        try:
            import ctypes

            vol = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetVolumeInformationW(
                "C:\\", None, 0, ctypes.byref(vol), None, None, None, 0
            )
            parts.append("vol:%08X" % (vol.value & 0xFFFFFFFF))
        except Exception:
            pass
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as h:
                g, _ = winreg.QueryValueEx(h, "MachineGuid")
                parts.append("guid:" + str(g))
        except Exception:
            pass

    try:
        import uuid as _uuid

        parts.append("mac:%012X" % _uuid.getnode())
    except Exception:
        pass

    if not parts:
        parts.append("host:" + os.environ.get("COMPUTERNAME", "unknown"))

    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16].upper()


def pretty_machine(mid: str) -> str:
    m = norm_key(mid)
    return "-".join(m[i:i + 4] for i in range(0, len(m), 4)) if m else ""


def machine_matches(rec_machine: str, this_machine: str) -> bool:
    return norm_key(rec_machine) == norm_key(this_machine)


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def verify(
    store: dict,
    app_id: str,
    key: str,
    machine: str = "",
    secret: str = "",
    consume: bool = False,
    require_sig: bool = True,
) -> dict:
    """校验一张卡密。

    返回 dict: {ok, code, reason, record, app}

    consume=True 时，成功后会把 uses+1 / 首次绑定机器写回 record（由调用方负责推回仓库）。
    require_sig=True（默认）时，配置了 secret 就必须校验签名，缺签名一律拒绝。
    """
    out = {"ok": False, "code": "KEY_NOT_FOUND", "reason": REASON_TEXT["KEY_NOT_FOUND"],
           "record": None, "app": None}

    nk = norm_key(key)
    if not nk:
        out.update(code="BAD_INPUT", reason=REASON_TEXT["BAD_INPUT"])
        return out

    if secret and not check_sig(store, secret, require=require_sig):
        out.update(code="SIG_INVALID", reason=REASON_TEXT["SIG_INVALID"])
        return out

    apps = store.get("apps") or {}
    app = apps.get(app_id)
    if not app:
        out.update(code="APP_NOT_FOUND", reason=REASON_TEXT["APP_NOT_FOUND"])
        return out
    out["app"] = app

    rec = (app.get("keys") or {}).get(nk)
    if not rec:
        return out
    out["record"] = rec

    now = time.time()

    if rec.get("revoked"):
        out.update(code="REVOKED", reason=REASON_TEXT["REVOKED"])
        return out

    exp = _parse_iso(rec.get("expire"))
    if exp and now > exp:
        out.update(code="EXPIRED", reason=REASON_TEXT["EXPIRED"])
        return out

    start = _parse_iso(rec.get("created"))
    if start and now + 86400 < start:
        out.update(code="NOT_YET_VALID", reason=REASON_TEXT["NOT_YET_VALID"])
        return out

    mu = int(rec.get("max_uses") or 0)
    if mu and int(rec.get("uses") or 0) >= mu and not rec.get("machine"):
        out.update(code="EXHAUSTED", reason=REASON_TEXT["EXHAUSTED"])
        return out

    if machine:
        bound = (rec.get("bind_machine") or "").replace("-", "")
        used_by = (rec.get("machine") or "").replace("-", "")
        if bound and not machine_matches(bound, machine):
            out.update(code="MACHINE_MISMATCH", reason=REASON_TEXT["MACHINE_MISMATCH"])
            return out
        if used_by and not machine_matches(used_by, machine):
            out.update(code="MACHINE_MISMATCH", reason=REASON_TEXT["MACHINE_MISMATCH"])
            return out

    # 通过
    out.update(ok=True, code="OK", reason=REASON_TEXT["OK"])

    if consume:
        first_use = not rec.get("machine")
        if machine and first_use and rec.get("bind_on_first_use"):
            rec["machine"] = pretty_machine(machine)
        if mu:
            rec["uses"] = int(rec.get("uses") or 0) + 1
        rec["last_used"] = now_iso()

    return out


# --------------------------------------------------------------------------
# HTTP 小工具
# --------------------------------------------------------------------------

def _ssl_ctx():
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def http_get(url: str, headers: dict | None = None, timeout: int = 15):
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Cache-Control", "no-cache")
    req.add_header("Pragma", "no-cache")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return r.status, r.read(), dict(r.headers)


def http_put(url: str, payload: dict, headers: dict | None = None, timeout: int = 20):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return r.status, r.read()


def _bust(url: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={int(time.time())}"


# --------------------------------------------------------------------------
# GitHub 仓库读写
# --------------------------------------------------------------------------

class GitHubStore:
    """把 GitHub 仓库里的一个 JSON 文件当数据库用。

    repo      : "owner/repo"
    path      : 仓库内文件路径，例如 "keys.json"
    branch    : 分支名，默认 main
    token     : 写操作必填（PAT，classic 勾 repo，或 fine-grained 勾 Contents: RW）
    raw_url   : 直接指定 raw 地址（用 Gist 或自建 CDN 时填这个，优先于 repo/path）
    """

    def __init__(self, repo: str = "", path: str = DEFAULT_PATH,
                 branch: str = DEFAULT_BRANCH, token: str = "", raw_url: str = ""):
        self.repo = (repo or "").strip().strip("/")
        self.path = (path or DEFAULT_PATH).lstrip("/")
        self.branch = branch or DEFAULT_BRANCH
        self.token = (token or "").strip()
        self._raw_override = (raw_url or "").strip()

    # ---- 地址 ----
    @property
    def api_url(self) -> str:
        return f"{GITHUB_API}/repos/{self.repo}/contents/{urllib.parse.quote(self.path)}"

    @property
    def raw_url(self) -> str:
        if self._raw_override:
            return self._raw_override
        return f"{RAW_HOST}/{self.repo}/{self.branch}/{self.path}"

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    # ---- 读 ----
    def read(self, prefer_api: bool = True) -> tuple[dict, str | None]:
        """返回 (store, sha)。failed 时抛异常。"""
        last_err: Exception | None = None

        if prefer_api and not self._raw_override and self.repo:
            try:
                url = _bust(f"{self.api_url}?ref={urllib.parse.quote(self.branch)}")
                status, raw, _ = http_get(url, self._headers())
                meta = json.loads(raw.decode("utf-8"))
                content = meta.get("content") or ""
                text = base64.b64decode(content).decode("utf-8")
                return load_store_text(text), meta.get("sha")
            except Exception as e:  # noqa: BLE001
                last_err = e

        try:
            status, raw, _ = http_get(_bust(self.raw_url))
            return load_store_text(raw.decode("utf-8")), None
        except Exception as e:  # noqa: BLE001
            last_err = e

        raise RuntimeError(f"读取卡密库失败：{last_err}")

    # ---- 写 ----
    def write(self, store: dict, message: str = "update keys", sha: str | None = None,
              secret: str = "") -> str:
        """写回仓库，返回新的 sha。需要 token。"""
        if not self.token:
            raise RuntimeError("缺少 GitHub Token，无法写回仓库")
        if secret:
            sign_store(store, secret)

        if sha is None:
            try:
                _, s = self.read(prefer_api=True)
                sha = s
            except Exception:
                sha = None

        text = dump_store(store, pretty=True)
        payload = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha

        status, raw = http_put(self.api_url, payload, self._headers())
        if status not in (200, 201):
            raise RuntimeError(f"写入失败，HTTP {status}: {raw[:200]!r}")
        return json.loads(raw.decode("utf-8")).get("content", {}).get("sha", "")

    def check(self) -> dict:
        """连通性自检，给管理端的【测试连接】按钮用。"""
        info = {"ok": False, "api": False, "raw": False, "keys": 0, "sha": None, "error": ""}
        try:
            store, sha = self.read(prefer_api=True)
            info["ok"] = True
            info["api"] = True
            info["sha"] = sha
            info["keys"] = sum(len(a.get("keys") or {}) for a in (store.get("apps") or {}).values())
            info["apps"] = list((store.get("apps") or {}).keys())
            return info
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
        try:
            _, _, _ = http_get(_bust(self.raw_url))
            info["raw"] = True
        except Exception:
            pass
        return info


# --------------------------------------------------------------------------
# 本地授权缓存 license.dat
# --------------------------------------------------------------------------

def license_sig(app_id: str, key: str, machine: str, secret: str = "") -> str:
    """本地授权文件 license.dat 的签名。

    配了 secret -> 用 HMAC-SHA256。这是必须的：早期版本用的是「公开输入的普通
    SHA256」，公式写在公开仓库里，任何人都能照着算出一个合法签名，
    从而伪造 license.dat 白嫖（实测可绕过）。
    没配 secret -> 退回普通 SHA256，此时 license.dat 依然可伪造，仅用于明文模式。
    """
    msg = f"{app_id}|{norm_key(key)}|{norm_key(machine)}".encode("utf-8")
    if secret:
        return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hashlib.sha256(msg).hexdigest()


def make_license(app_id: str, key: str, machine: str, secret: str = "") -> dict:
    return {
        "app_id": app_id,
        "key": pretty_key(key),
        "machine": pretty_machine(machine),
        "issued": now_iso(),
        "sig": license_sig(app_id, key, machine, secret),
        "v": 2 if secret else 1,
    }


def check_license(lic: dict, app_id: str, machine: str, secret: str = "") -> bool:
    if not isinstance(lic, dict):
        return False
    if lic.get("app_id") != app_id:
        return False
    if not machine:
        return True
    return hmac.compare_digest(
        str(lic.get("sig", "")),
        license_sig(app_id, lic.get("key", ""), lic.get("machine", ""), secret),
    ) and machine_matches(lic.get("machine", ""), machine)


def default_license_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "cardkey-gate", "license.dat")


def save_license(lic: dict, path: str = "") -> str:
    path = path or default_license_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lic, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load_license(path: str = "") -> dict | None:
    path = path or default_license_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
