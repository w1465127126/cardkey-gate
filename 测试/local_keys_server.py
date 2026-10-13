#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_keys_server.py — 本地假卡密库（测试用，不需要 GitHub）

在自己电脑上起一个 HTTP 服务冒充 GitHub raw，用来验证整套流程。

用法：
    python local_keys_server.py                # 监听 127.0.0.1:8899
    python local_keys_server.py 9000           # 换端口

启动后会打印一张随机生成的有效卡密，例如：
    GOOD=QXE3-9CPF-XWUC-XNTH
    READY

另开一个窗口测试（Windows 上要加 NO_PROXY，否则本机代理会劫持 127.0.0.1）：

    set NO_PROXY=127.0.0.1,localhost
    ② 卡密校验器.exe --check QXE3-9CPF-XWUC-XNTH --app-id MY_APP ^
                     --raw-url http://127.0.0.1:8899/keys.json
"""

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# 源码在上一级的 源码\ 目录里
for cand in (os.path.join(HERE, "..", "源码"), os.path.join(HERE, ".."), HERE):
    if os.path.isfile(os.path.join(cand, "cardkey_store.py")):
        sys.path.insert(0, os.path.abspath(cand))
        break
else:
    sys.exit("找不到 cardkey_store.py，请把本脚本放在 卡密系统\\测试\\ 目录下运行")

import cardkey_store as cs  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
DB = os.path.join(HERE, "keys_live.json")

st = cs.empty_store()
good = cs.add_key(st, "MY_APP", note="local-test", days=30, max_uses=0)[0]
expired = cs.add_key(st, "MY_APP", note="expired", days=1)[0]
cs.get_record(st, "MY_APP", expired)["expire"] = "2000-01-01T00:00:00Z"
revoked = cs.add_key(st, "MY_APP", note="revoked")[0]
cs.revoke_key(st, "MY_APP", revoked)
with open(DB, "w", encoding="utf-8") as f:
    f.write(cs.dump_store(st))


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            with open(DB, "rb") as f:
                b = f.read()
        except Exception:
            b = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


print(f"GOOD={good}", flush=True)
print(f"EXPIRED={expired}", flush=True)
print(f"REVOKED={revoked}", flush=True)
print(f"READY http://127.0.0.1:{PORT}/keys.json", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
