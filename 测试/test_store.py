#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自测：卡密生成、校验、机器绑定、吊销、过期、次数、签名、序列化往返。"""

import json
import os
import sys
import time

# 源码可能在 上一级\源码\（桌面整合版） 或 上一级\（开发目录）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.join(_HERE, "..", "源码"), os.path.join(_HERE, ".."), _HERE):
    if os.path.isfile(os.path.join(_c, "cardkey_store.py")):
        sys.path.insert(0, os.path.abspath(_c))
        break
import cardkey_store as cs  # noqa: E402

PASS = FAIL = 0


def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def main():
    print("\n=== 1. 卡密生成与规范化 ===")
    k = cs.gen_key()
    chk("格式 XXXX-XXXX-XXXX-XXXX", len(k.split("-")) == 4 and all(len(p) == 4 for p in k.split("-")), k)
    chk("字符集不混淆", not (set(cs.norm_key(k)) & set("0O1IL5S28BZ")), k)
    chk("规范化解连字符", cs.norm_key(k) == k.replace("-", ""))
    chk("小写可还原", cs.pretty_key(cs.norm_key(k.lower())) == k)
    chk("去分隔符容错", cs.norm_key("abcd efgh-jklm_npqr") == cs.norm_key(k) or len(cs.norm_key("abcd efgh-jklm_npqr")) == 16)

    print("\n=== 2. 建库 / 加卡密 / 序列化往返 ===")
    st = cs.empty_store()
    keys = cs.add_key(st, "APP1", note="测试", days=30, max_uses=1, count=5, app_name="我的工具")
    chk("批量生成 5 张", len(keys) == 5, len(keys))
    chk("无重复", len(set(cs.norm_key(x) for x in keys)) == 5)
    text = cs.dump_store(st)
    st2 = cs.load_store_text(text)
    chk("JSON 往返一致", json.dumps(st2["apps"], sort_keys=True) == json.dumps(st["apps"], sort_keys=True))
    chk("app 名保留", st2["apps"]["APP1"]["name"] == "我的工具")

    print("\n=== 3. 正常校验 ===")
    k0 = keys[0]
    r = cs.verify(st, "APP1", k0)
    chk("有效卡密通过", r["ok"] and r["code"] == "OK", r)
    chk("小写+无分隔符也通过", cs.verify(st, "APP1", k0.replace("-", "").lower())["ok"])

    print("\n=== 4. 错误分支 ===")
    chk("不存在的卡密", cs.verify(st, "APP1", "AAAA-BBBB-CCCC-DDDD")["code"] == "KEY_NOT_FOUND")
    chk("APP_ID 不存在", cs.verify(st, "NOPE", k0)["code"] == "APP_NOT_FOUND")
    chk("空输入", cs.verify(st, "APP1", "  ")["code"] == "BAD_INPUT")

    print("\n=== 5. 吊销 / 恢复 ===")
    cs.revoke_key(st, "APP1", keys[1])
    chk("吊销后拒绝", cs.verify(st, "APP1", keys[1])["code"] == "REVOKED")
    cs.revoke_key(st, "APP1", keys[1], False)
    chk("恢复后通过", cs.verify(st, "APP1", keys[1])["ok"])

    print("\n=== 6. 过期 ===")
    st_exp = cs.empty_store()
    ek = cs.add_key(st_exp, "APP1", days=1)[0]
    rec = cs.get_record(st_exp, "APP1", ek)
    rec["expire"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    chk("过期拒绝", cs.verify(st_exp, "APP1", ek)["code"] == "EXPIRED")
    pk = cs.add_key(st_exp, "APP1", days=0)[0]
    chk("永久卡不过期", cs.verify(st_exp, "APP1", pk)["ok"])

    print("\n=== 7. 次数限制 ===")
    st_u = cs.empty_store()
    uk = cs.add_key(st_u, "APP1", max_uses=3)[0]
    chk("第1次通过", cs.verify(st_u, "APP1", uk, consume=True)["ok"])
    cs.verify(st_u, "APP1", uk, consume=True)
    cs.verify(st_u, "APP1", uk, consume=True)
    chk("超过3次拒绝", cs.verify(st_u, "APP1", uk)["code"] == "EXHAUSTED")
    chk("uses 计数=3", cs.get_record(st_u, "APP1", uk)["uses"] == 3)

    print("\n=== 8. 机器绑定 ===")
    st_m = cs.empty_store()
    mk = cs.add_key(st_m, "APP1", bind_machine="AAAA1111BBBB2222", max_uses=0)[0]
    chk("绑定机器通过", cs.verify(st_m, "APP1", mk, machine="AAAA1111BBBB2222")["ok"])
    chk("其它机器拒绝", cs.verify(st_m, "APP1", mk, machine="CCCC3333DDDD4444")["code"] == "MACHINE_MISMATCH")
    chk("带连字符机器码也匹配", cs.verify(st_m, "APP1", mk, machine="AAAA-1111-BBBB-2222")["ok"])

    st_f = cs.empty_store()
    fk = cs.add_key(st_f, "APP1", bind_on_first_use=True, max_uses=0)[0]
    cs.verify(st_f, "APP1", fk, machine="EEEE5555FFFF6666", consume=True)
    chk("首用自动绑机器", (cs.get_record(st_f, "APP1", fk).get("machine") or "").replace("-", "") == "EEEE5555FFFF6666")
    chk("换机器被拦", cs.verify(st_f, "APP1", fk, machine="1111AAAA2222BBBB")["code"] == "MACHINE_MISMATCH")

    print("\n=== 9. 签名 ===")
    st_s = cs.empty_store()
    cs.add_key(st_s, "APP1", count=1)
    cs.sign_store(st_s, "mysecret")
    chk("正确签名通过", cs.verify(st_s, "APP1", next(iter(st_s["apps"]["APP1"]["keys"])), secret="mysecret")["ok"])
    bad = json.loads(json.dumps(st_s))
    bad["apps"]["APP1"]["keys"]["ZZZZ"] = {"revoked": False, "uses": 0}
    chk("被篡改拒绝", cs.verify(bad, "APP1", next(iter(st_s["apps"]["APP1"]["keys"])), secret="mysecret")["code"] == "SIG_INVALID")

    # 关键：把 sig 字段整个删掉也必须拒绝，否则等于没开签名
    stripped = json.loads(json.dumps(st_s))
    stripped.pop("sig", None)
    chk("抹掉 sig 字段也拒绝",
        cs.verify(stripped, "APP1", next(iter(st_s["apps"]["APP1"]["keys"])), secret="mysecret")["code"] == "SIG_INVALID")
    chk("require_sig=False 时无签名放行",
        cs.verify(stripped, "APP1", next(iter(st_s["apps"]["APP1"]["keys"])), secret="mysecret", require_sig=False)["ok"])
    chk("不配 secret 时明文可用",
        cs.verify(stripped, "APP1", next(iter(st_s["apps"]["APP1"]["keys"])))["ok"])
    chk("check_sig 不污染原字典", "sig" not in stripped)

    print("\n=== 10. 本地授权文件 ===")
    mid = cs.machine_id()
    chk("机器码16位", len(mid) == 16, mid)
    lic = cs.make_license("APP1", keys[0], mid)
    chk("license 校验通过", cs.check_license(lic, "APP1", mid))
    chk("换机器失效", not cs.check_license(lic, "APP1", "DEADBEEFDEADBEEF"))
    chk("换 APP 失效", not cs.check_license(lic, "APP2", mid))

    # secret 模式下 license.dat 必须用 secret 签名，否则攻击者照着公开算法就能伪造
    lic_s = cs.make_license("APP1", keys[0], mid, "SEC1")
    chk("带 secret 的 license 通过", cs.check_license(lic_s, "APP1", mid, "SEC1"))
    chk("secret 不对则失效", not cs.check_license(lic_s, "APP1", mid, "SEC2"))
    forged = cs.make_license("APP1", "AAAA-BBBB-CCCC-DDDD", mid)
    chk("伪造 license 被拒（无 secret 签名）", not cs.check_license(forged, "APP1", mid, "SEC1"))
    chk("明文模式兼容普通 SHA256", cs.check_license(forged, "APP1", mid))
    chk("HMAC 版 sig 与明文版不同", cs.license_sig("APP1", keys[0], mid, "SEC1") != cs.license_sig("APP1", keys[0], mid))
    p = os.path.join(os.environ.get("TEMP", "/tmp"), "ck_test_lic.dat")
    cs.save_license(lic, p)
    chk("落盘再读一致", cs.load_license(p)["sig"] == lic["sig"])
    os.remove(p)

    print("\n=== 11. 管理端辅助 ===")
    chk("key_status 未使用", cs.key_status({"max_uses": 1, "uses": 0, "revoked": False}) == "未使用")
    chk("key_status 已吊销", cs.key_status({"revoked": True}) == "已吊销")
    chk("iter_keys 计数", len(list(cs.iter_keys(st))) == 5)
    chk("删除生效", cs.delete_key(st, "APP1", keys[4]) and len(list(cs.iter_keys(st))) == 4)

    print(f"\n{'='*46}\n结果：PASS={PASS}  FAIL={FAIL}\n{'='*46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
