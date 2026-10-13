#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端联网测试：本地起一个 HTTP 服务充当 GitHub raw，
让 SDK 真实走 urllib 走一遍 拉库 -> 校验 -> 写本地授权 的全流程。

不依赖外网，可在沙箱内跑。
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 源码可能在 上一级\源码\（桌面整合版） 或 上一级\（开发目录）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.join(_HERE, "..", "源码"), os.path.join(_HERE, ".."), _HERE):
    if os.path.isfile(os.path.join(_c, "cardkey_store.py")):
        sys.path.insert(0, os.path.abspath(_c))
        break
import cardkey_store as cs  # noqa: E402
import cardkey_sdk as sdk  # noqa: E402

PASS = FAIL = 0
HITS = []


def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


class Handler(BaseHTTPRequestHandler):
    payload = b"{}"
    status = 200

    def do_GET(self):
        HITS.append(self.path)
        self.send_response(Handler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(Handler.payload)))
        self.end_headers()
        self.wfile.write(Handler.payload)

    def log_message(self, *a):
        pass


def main():
    # ---- 造库 ----
    st = cs.empty_store()
    good = cs.add_key(st, "DEMO_APP", note="e2e", max_uses=0)[0]
    dead = cs.add_key(st, "DEMO_APP", note="revoked")[0]
    cs.revoke_key(st, "DEMO_APP", dead)
    exp = cs.add_key(st, "DEMO_APP", days=1)[0]
    cs.get_record(st, "DEMO_APP", exp)["expire"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    Handler.payload = cs.dump_store(st).encode("utf-8")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    raw = f"http://127.0.0.1:{port}/keys.json"
    print(f"\n本地卡密库: {raw}\n")

    sdk.CONFIG.update({"app_id": "DEMO_APP", "raw_url": raw, "repo": "", "path": "keys.json"})

    print("=== 1. 拉库 ===")
    st2 = sdk.fetch_store()
    chk("HTTP 拉取成功", "DEMO_APP" in st2.get("apps", {}))
    chk("请求被服务端收到", len(HITS) >= 1, HITS)

    print("\n=== 2. 有效卡密 ===")
    r = sdk.verify_key(good)
    chk("通过", r["ok"], r.get("reason"))

    print("\n=== 3. 已吊销卡密 ===")
    r = sdk.verify_key(dead)
    chk("拒绝 REVOKED", r["code"] == "REVOKED", r)

    print("\n=== 4. 已过期卡密 ===")
    r = sdk.verify_key(exp)
    chk("拒绝 EXPIRED", r["code"] == "EXPIRED", r)

    print("\n=== 5. 不存在的卡密 ===")
    r = sdk.verify_key("ZZZZ-9999-ZZZZ-9999")
    chk("拒绝 KEY_NOT_FOUND", r["code"] == "KEY_NOT_FOUND", r)

    print("\n=== 6. 坏 URL -> STORE_ERROR ===")
    sdk.CONFIG["raw_url"] = f"http://127.0.0.1:{port}/nope.json"
    Handler.status = 404
    r = sdk.verify_key(good)
    chk("返回 STORE_ERROR 不崩", r["code"] == "STORE_ERROR", r)
    Handler.status = 200
    sdk.CONFIG["raw_url"] = raw

    print("\n=== 7. 断网 -> 本地授权兜底 ===")
    lp = os.path.join(os.environ.get("TEMP", "/tmp"), "ck_e2e_lic.dat")
    cs.save_license(cs.make_license("DEMO_APP", good, cs.machine_id()), lp)
    lic = cs.load_license(lp)
    chk("本地授权写入并可读", bool(lic) and cs.check_license(lic, "DEMO_APP", cs.machine_id()))
    sdk.CONFIG["raw_url"] = "http://127.0.0.1:1/none.json"   # 必然连不上
    sdk.CONFIG["offline_grace_days"] = 30
    node = sdk.gate(force_prompt=False, cache_path=lp)   # 有本地授权 -> 应直接放行
    chk("离线时用本地授权放行", node is True)
    os.remove(lp)

    print("\n=== 8. 一次完整的 gate（模拟用户输错再输对） ===")
    sdk.CONFIG["raw_url"] = raw
    answers = iter([good.lower().replace("-", ""), good])
    orig = sdk._ask_gui
    sdk._ask_gui = lambda *a, **k: next(answers, None)
    sdk._toast_ok = lambda *a, **k: None
    sdk._toast_err = lambda *a, **k: None
    lp2 = os.path.join(os.environ.get("TEMP", "/tmp"), "ck_e2e_lic2.dat")
    ok = sdk.gate(force_prompt=True, cache_path=lp2)
    sdk._ask_gui = orig
    chk("第一次输入无效被拦、第二次通过", ok is True)
    chk("通过后落盘本地授权", os.path.exists(lp2))
    if os.path.exists(lp2):
        os.remove(lp2)

    srv.shutdown()

    print(f"\n{'='*46}\n端到端结果：PASS={PASS}  FAIL={FAIL}\n{'='*46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
