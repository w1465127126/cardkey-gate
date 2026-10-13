# cardkey-gate · 卡密门禁系统

自建卡密系统：**你在管理端生成卡密 → 推送到 GitHub 仓库 → 受保护程序启动时弹框输入卡密 → 联网校验 → 放行**。

按需求方要求，安全强度保持"能用就行"（卡密库存 GitHub 明文 JSON）。

```
cardkey-gate/
├── cardkey_store.py        # 核心库（纯标准库，离网可测）
├── keygen_gui.py           # ★ 卡密管理端 GUI —— 你用的
├── cardkey_sdk.py          # 受保护程序接入用的 SDK
├── keycheck_cli.py         # 控制台校验器（给 bat 调用）
├── demo_protected_app.py   # 示例受保护程序（改 main_window() 变成你的）
├── keys.json               # 卡密库（含 HMAC 签名）—— 传到 GitHub 仓库
├── build.bat               # 一键打包 exe
├── app_config.json.example # 配置模板（app_config.json 含 token/secret，已 gitignore）
├── keycheck.json.example   # 校验器配置模板（keycheck.json 含 secret，已 gitignore）
├── tests/
│   ├── test_store.py       # 41 项离线自测（已全绿）
│   └── test_e2e_http.py    # 11 项端到端 HTTP 测试（已全绿）
└── dist/                   # ← 编译产物，不在仓库里
    ├── CardKeyManager.exe  # 管理端（9.1 MB）
    ├── KeyCheck.exe        # 控制台校验器
    └── DemoApp.exe         # 示例受保护程序
```

> **三个 exe 不放在仓库里**，走 **[Releases](https://github.com/w1465127126/cardkey-gate/releases)** 下载
> （仓库只留源码，克隆快、diff 干净）。想自己编译看第六节。

---

## 一、5 分钟上手

### 1) 建 GitHub 仓库放卡密库

新建仓库（**私有仓库也能用**，只要客户端带 token；公共仓库不用 token 即可读）：

1. 仓库里新建文件 `keys.json`，内容就复制本目录的 `keys.json`
2. 生成访问令牌：GitHub → Settings → Developer settings → Personal access tokens
   - Classic：勾 `repo`（私有仓库）或 `public_repo`（公共仓库）
   - Fine-grained：Repository permissions → **Contents: Read and write**
3. 记下 `owner/repo`，例如 `duoduo/my-keys`

### 2) 打开管理端

双击 `dist\CardKeyManager.exe`，顶部填：

| 字段 | 填什么 |
|---|---|
| 仓库 owner/repo | `duoduo/my-keys` |
| 文件路径 | `keys.json` |
| 分支 | `main` |
| PAT Token | 上一步的令牌 |
| HMAC secret | 留空即可（想防篡改再填，见第五节） |

点 **测试连接** → 出现 `✅ 已连接 sha=abc1234 卡密 1 张` 就算通了。

### 3) 生成卡密

在"② 生成卡密"区填：

| 字段 | 说明 |
|---|---|
| APP_ID | 给这个软件的编号，**要和受保护程序里的一致**。例如 `MY_TOOL` |
| 显示名 | 备注用，例如 `我的工具` |
| 备注 | 例如 "2026双十一活动" |
| 有效期(天) | `0`=永久；`30`=30天 |
| 次数(0=不限) | `1`=只能激活一台/一次；`0`=不限 |
| 生成数量 | 一次要几张 |
| 绑定机器码 | 空=不绑；填了就**只能那台机器用** |
| 首次使用自动绑定机器 | 勾上=谁先用就锁谁 |

点 **生成卡密** → 点 **推送仓库** → 生效。列表里能看到状态（未使用/已激活/已过期/已吊销）。

> 「我的机器码」按钮可以拿本机机器码，用来做单机绑定。

### 4) 让程序弹框要卡密

**Python 程序**，加三行：

```python
import cardkey_sdk

if not cardkey_sdk.gate(
    app_id="MY_TOOL",
    repo="duoduo/my-keys",
    raw_url="https://raw.githubusercontent.com/duoduo/my-keys/main/keys.json",
):
    raise SystemExit
# ↓ 下面是你的程序本体
```

**非 Python 程序（bat / 快捷方式 / 任何 exe）**，用 `KeyCheck.exe` 先卡一道：

```bat
@echo off
chcp 65001 >nul
"%~dp0KeyCheck.exe" --check %1
if errorlevel 1 (
    echo.
    echo [X] 卡密无效或已过期，程序退出。
    pause
    exit /b 1
)
start "" "MyRealApp.exe"
```

同目录放一个 `keycheck.json` 告诉它去哪查：

```json
{
  "repo": "duoduo/my-keys",
  "path": "keys.json",
  "branch": "main",
  "app_id": "MY_TOOL",
  "secret": ""
}
```

---

## 二、卡密库格式（keys.json）

```json
{
  "version": 1,
  "updated": "2026-10-13T07:40:00Z",
  "apps": {
    "MY_TOOL": {
      "name": "我的工具",
      "keys": {
        "ACDE3467GHJK9MNP": {
          "key": "ACDE-3467-GHJK-9MNP",
          "note": "双十一活动",
          "created": "2026-10-13T07:40:00Z",
          "expire": "2026-11-12T07:40:00Z",
          "max_uses": 1,
          "uses": 0,
          "bind_machine": "",
          "bind_on_first_use": true,
          "machine": "",
          "revoked": false,
          "last_used": ""
        }
      }
    }
  }
}
```

| 字段 | 含义 |
|---|---|
| `expire` | `null`=永久；否则 UTC 时间，格式 `%Y-%m-%dT%H:%M:%SZ` |
| `max_uses` | `0`=不限次数 |
| `bind_machine` | 预先指定的机器码（16 位，可带连字符） |
| `bind_on_first_use` | `true`=首次校验成功后自动写入 `machine` |
| `machine` | 实际绑定的机器码 |
| `revoked` | `true`=立即作废 |

一个仓库可以放很多 `apps`，一个 APP_ID 对应一个软件，互不干扰。

---

## 三、校验结果码

| code | 界面提示 | 含义 |
|---|---|---|
| `OK` | 验证通过 | 放行 |
| `KEY_NOT_FOUND` | 卡密不存在或输入有误 | 打错了，或没推送仓库 |
| `APP_NOT_FOUND` | 找不到这个应用 ID | APP_ID 写错 / 库里没这个应用 |
| `REVOKED` | 该卡密已被吊销 | 管理端点了吊销，立刻生效 |
| `EXPIRED` | 该卡密已过期 | 超有效期 |
| `EXHAUSTED` | 可用次数已用尽 | `uses >= max_uses` |
| `MACHINE_MISMATCH` | 已绑定其它机器 | 想换机用 |
| `STORE_ERROR` | 无法读取卡密库 | 网络断 / 仓库地址错 / token 失效 |
| `SIG_INVALID` | 卡密库签名校验失败 | 有人手改了 JSON |
| `BAD_INPUT` | 请填写卡密 | 空输入 |

---

## 四、发卡怎么落地

1. 管理端生成 → **导出 TXT**（自动存桌面 `keys_时间戳.txt`）或 **复制本次生成的卡密**
2. 发给买家/朋友，让他启动程序粘贴
3. 想作废：列表里选中 → **吊销选中** → **推送仓库**。对方下次联网校验就会看到"已吊销"
   - 拉库走的是 GitHub Contents API，**绕开 CDN 缓存**，吊销后基本立即生效（实测 < 1 分钟）

**离线容错**：通过一次后写 `%APPDATA%\cardkey-gate\license.dat`，30 天内断网也能进；
超过 30 天必须联网复核一次。想改成每次都要联网，把 `gate(..., offline_grace_days=0)`。

> ⚠️ **只有"真的拉不到库"才走离线容错。** `gate()` 收到 `STORE_ERROR` / `OFFLINE`
> 才放行；`KEY_NOT_FOUND` / `REVOKED` / `EXPIRED` 之类属于"库说不行"，一律判失效并
> 清除本地授权。早期版本把 `KEY_NOT_FOUND` 也当成网络问题放行，配合下面这个坑
> 就能白嫖 —— 现在两条都堵上了。

> ⚠️ **配了 secret 后，`license.dat` 的签名是 HMAC-SHA256**，拿不到 secret 就伪造不出来。
> 没配 secret 时退回普通 SHA256 —— 公式是公开的，任何人都能照着造一份合法授权文件。
> **想真正挡住白嫖，secret 必须配。**

---

## 五、可选：开启 HMAC 签名（防手改 JSON）

不填 secret 时，卡密库是明文、谁拿到都能伪造。在乎的话：

1. 管理端 `HMAC secret` 填一个随机串（比如 `openssl rand -hex 16`），**推送时会自动给库签名**
2. SDK 侧也填同样的 secret：
   ```python
   cardkey_sdk.gate(app_id="MY_TOOL", repo="...", raw_url="...", secret="你的随机串")
   ```
   或者写进 `CONFIG["secret"]`
3. 之后任何人改了 `apps` 里的内容，`sig` 就对不上 → 直接 `SIG_INVALID` 拒绝
4. **删掉 `sig` 字段同样被拒**。`check_sig()` 默认 `require=True`：只要配了 secret，
   库就必须带有效签名，缺签名 = 拒绝。否则攻击者把 `sig` 一删就能绕过全部签名校验。
   过渡期若还想跑明文库，显式传 `require_sig=False`。

> ⚠️ **secret 绝对不能进仓库。** 公开仓库里的任何文件都是全世界可见的，
> 把 secret 写进 `keycheck.json` / `app_config.json` 一起推上去，等于没开签名。
> 这两个文件都已在 `.gitignore` 里，仓库里只留 `.example` 模板。

代价：secret 内嵌在 exe 里，会逆向的人能抠出来。只挡顺手改 JSON 的人。

---

## 六、自己打包 exe

```bat
build.bat
```

或在项目目录手动：

```bat
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
  --name CardKeyManager --distpath dist --workpath build --specpath build keygen_gui.py
```

受保护程序打包（带 SDK）：

```bat
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
  --name MyApp --distpath dist --workpath build --specpath build ^
  --hidden-import cardkey_store --hidden-import cardkey_sdk MyApp.py
```

> 环境要求：Python 3.10+（本项目用 `C:\Program Files\Python310` 建的 venv，自带 tkinter）。
> 若你的 Python 没带 tkinter，装一遍官方安装包并勾上 `tcl/tk`。

---

## 七、自测

```bat
.venv\Scripts\python.exe tests\test_store.py       :: 37 项：生成/校验/绑定/吊销/过期/次数/签名
.venv\Scripts\python.exe tests\test_e2e_http.py    :: 11 项：真实 HTTP 拉库 -> 校验 -> 落盘授权
```

当前状态：**52 项全绿**。

---

## 八、常见问题

**Q：客户端要放 token 吗？**
公共仓库不用。私有仓库得放一个只读 token，但 token 会随 exe 发出去 —— 这也是"不在乎安全性"的常见做法。折中：公共仓库 + HMAC secret。

**Q：为什么不用 `raw.githubusercontent.com` 直接读？**
它走 CDN，最长缓存 5 分钟，吊销不能立刻生效。所以客户端优先走 Contents API（带 `Cache-Control: no-cache`），失败才回落 raw。

**Q：GitHub 的 API 限流？**
未认证 60 次/小时（按 IP）。够用；如果用户量很大，在 SDK 里塞个只读 token 可提到 5000 次/小时。

**Q：卡密刷不出新状态？**
客户端有本地授权缓存，正常情况下不再联网。管理端点吊销后，客户端下一次复核周期（默认 30 天）才会感知。想催：删 `%APPDATA%\cardkey-gate\license.dat`，或把 `offline_grace_days` 调小。

**Q：能换 Gitee / 自建服务器吗？**
能。`GitHubStore` 的 `raw_url` 参数直接吃任意 HTTP JSON 地址，写操作换成你自己的 PUT 接口即可。管理端的"推送"逻辑在 `keygen_gui.py` 的 `on_push()`，改这里就行。

---

## 九、本仓库当前部署状态

| 项 | 值 |
|---|---|
| 仓库 | `w1465127126/cardkey-gate` —— **公开（public）** |
| 卡密库 | 根目录 `keys.json`，带 `sig`（HMAC-SHA256）签名 |
| 客户端读取 | 不需要 token：`https://raw.githubusercontent.com/w1465127126/cardkey-gate/main/keys.json` |
| 管理端写入 | `%USERPROFILE%\.cardkey-gate\config.json` 里配 `repo` + `token` + `secret` |
| 签名状态 | **已启用**。篡改 `apps` 或删掉 `sig` 一律 `SIG_INVALID` |
| exe 分发 | 不在仓库里，走 [Releases](https://github.com/w1465127126/cardkey-gate/releases) |

**secret 不在本仓库内**，只存在于两处本地文件（均已被 `.gitignore` 排除）：
`%USERPROFILE%\.cardkey-gate\config.json`（管理端/校验器读取）和 exe 同目录的 `keycheck.json`。

这样一来客户端不需要内嵌任何 token，仓库被公开也不会泄露发卡能力——因为
改库需要 GitHub 写权限、伪造库需要 secret，两者都不在仓库里。

**签名强度实测**（用真实 exe 二进制对比，能复现的就是真的）：

| 场景 | 加固前 exe | 加固后 exe |
|---|---|---|
| 签名正确 | 放行 | 放行 |
| 篡改 `apps` 内容 | 拒绝 | 拒绝 |
| **直接删掉 `sig` 字段** | **放行（漏洞）** | **拒绝** |
| **伪造 `license.dat`** | **放行（漏洞）** | **拒绝** |
| **库里不存在的卡密 + 合法签名的授权文件** | **放行（漏洞）** | **拒绝** |

---

## 十、接入到现成的 exe（外挂式启动器）

目标程序不是自己写的、甚至没有源码（Nuitka / PyInstaller 编译成品、别人的 exe）时，
**不要去改它内部** —— 用启动器套一层：双击启动器 → 先过卡密 → 再拉起主体。

```
你的程序\
├── 你的程序.exe        ← 卡密启动器（我们的，占用原文件名，快捷方式不用改）
├── AlbionCore.exe      ← 真正的主体（原名改过来，依赖的 DLL 都还在同目录）
└── 卡密授权说明（先看我）.txt
```

启动器核心十来行：

```python
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cardkey_sdk as sdk

APP_ID  = "ALBION_FISH"
REPO    = "w1465127126/cardkey-gate"
RAW_URL = "https://raw.githubusercontent.com/w1465127126/cardkey-gate/main/keys.json"
SECRET  = "……"                 # 编译进 exe
CORE    = "AlbionCore.exe"

def app_dir():
    return os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))

if sdk.gate(app_id=APP_ID, repo=REPO, raw_url=RAW_URL, secret=SECRET,
            title="你的程序 · 授权验证"):
    subprocess.Popen([os.path.join(app_dir(), CORE)], cwd=app_dir(),
                     creationflags=0x00000008)      # DETACHED_PROCESS
    sys.exit(0)
sys.exit(1)
```

打包用 `pyinstaller --onefile --windowed --hidden-import tkinter --hidden-import tkinter.ttk
--hidden-import tkinter.messagebox`，产物改名成主体原来的文件名即可。

**两个必踩的坑**（都实测过）：

1. **绝不能把主体所在目录加进 `sys.path`。** 那里通常有 `python312.dll` / `_ssl.pyd`，
   与启动器自己的解释器版本不同，一导入 `ssl` 就报
   `ImportError: Module use of python312.dll conflicts with this version of Python`。
   启动器自己的目录（`__file__`）可以加，主体目录不行。
2. **配置必须编译进 exe，不要读同目录的 json。** 一旦读外部文件，
   买家把 `secret` 改成空串、`raw_url` 指到自己的仓库，门禁就完全失效了。

**能挡到什么程度**：挡得住"转发给别人用""换个 key 白嫖"这类普通用户；
挡不住会用调试器/十六进制编辑器改启动器的人 —— 客户端里的任何限制都是这样。
真在意就把核心校验放服务端。
