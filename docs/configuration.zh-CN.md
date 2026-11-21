# 配置参考

[English](configuration.md) | **简体中文**

bpy-bridge 暴露的每一个可调项，包含默认值以及修改它实际会改变什么。这里没列出的设置就是不存在 —— 本页是对照源码核过的，不是凭记忆写的。

- [默认值一览](#默认值一览)
- [启动服务](#启动服务)
- [Token](#token)
- [网络设置](#网络设置)
- [限制与超时](#限制与超时)
- [CLI 参考](#cli-参考)
- [Python 客户端参考](#python-客户端参考)
- [退出码](#退出码)
- [自启动](#自启动)
- [按症状排查](#按症状排查)

---

## 默认值一览

| 设置 | 默认值 | 所在位置 |
|---|---|---|
| 绑定主机 | `127.0.0.1` | `DEFAULT_HOST` |
| 端口 | `9876` | `DEFAULT_PORT` |
| Token | 随机 256 位，首次启动生成 | `~/.bpy-bridge/token` |
| Token 目录覆盖 | *（未设置）* | 环境变量 `BPY_BRIDGE_HOME` |
| 请求超时 | `600.0` 秒 | `DEFAULT_TIMEOUT` |
| 最大帧大小 | 4 MiB（`4194304` 字节） | `MAX_FRAME_BYTES` |
| 协议版本 | `1` | `PROTOCOL_VERSION` |
| 主线程泵间隔 | `0.02` 秒 | `_PUMP_INTERVAL` |
| 每次泵处理任务数 | `8` | `_PUMP_BATCH` |

这些是完全不做任何配置时得到的值。每一项都可覆盖；没有任何一项需要配置文件。

---

## 启动服务

### 从 Blender 的 Python 控制台

最短路径。按 `Shift+F4`，然后：

```python
exec(compile(open(r"/path/to/server.py", encoding="utf-8").read(),
             "bpy_bridge_server", "exec"))
```

这会以全部默认值调用 `start()`。服务会一直活着，直到 Blender 退出，或者你调用 `stop()`。

### 用 Python，带参数

当 `server.py` 能以模块形式被 import 时（例如作为自启动脚本的一部分被注入）：

```python
from bpy_bridge import server

server.start(
    port=9876,
    verbose=True,
)
```

`start()` 返回正在运行的 `BridgeServer` 实例。在服务已运行时再次调用，返回的是**同一个**实例而不是报错 —— 所以一个可能执行两次的脚本调用它是安全的。

### 用 Python，完全控制

`BridgeServer` 才是真正的类；`start()` 只是一个轻量便利封装。

```python
from bpy_bridge.server import BridgeServer

bridge = BridgeServer(
    host="127.0.0.1",
    port=9876,
    token_path=None,          # None -> ~/.bpy-bridge/token
    allow_remote=False,       # 要绑定非回环地址必须设为 True
    max_frame_bytes=4 * 1024 * 1024,
    persist_token=True,       # False 表示 token 不落盘
    namespace=None,           # None -> 全新的持久命名空间
)

bridge.start()      # 绑定端口、启动工作线程、注册泵
print(bridge.address)
print(bridge.info())

# ... 之后
bridge.stop()       # 重复调用是安全的
```

作为上下文管理器使用，退出时自动停止：

```python
with BridgeServer(port=9877) as bridge:
    print(bridge.address)
```

### 参数

| 参数 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `host` | `str` | `"127.0.0.1"` | 绑定的网卡。非回环值会抛 `ValueError`，除非 `allow_remote=True`。 |
| `port` | `int` | `9876` | TCP 端口。`0` 表示自动选一个空闲端口；之后从 `bridge.port` 读取真实端口。 |
| `token` | `str` | `None` | 显式指定的共享密钥。`None` 表示生成或复用。 |
| `token_path` | `str` | `None` | token 文件位置。`None` 使用 `~/.bpy-bridge/token`。 |
| `bpy_module` | module | `None` | `bpy` 模块。`None` 表示惰性 import —— 这正是服务端能在 Blender 之外被测试的原因。 |
| `allow_remote` | `bool` | `False` | 允许绑定非回环地址。 |
| `max_frame_bytes` | `int` | `4194304` | 单个请求或响应帧的硬上限。 |
| `namespace` | `dict` | `None` | 执行命名空间。`None` 创建全新的；传一个 dict 可与既有脚本共享状态。 |
| `persist_token` | `bool` | `True` | 是否把 token 写入磁盘。`False` 表示只放在内存里。 |

> **`persist_token=False` 是有后果的。** 客户端是通过读文件找到 token 的。如果你把它只留在内存里，
> 每个客户端都必须被显式告知 token（`--token` 或 `BridgeClient(token=...)`）。对一次性会话来说这是
> 合理选择，对其他一切场景都是陷阱。

---

## Token

### 它在哪

```
~/.bpy-bridge/token
```

用环境变量覆盖目录：

```bash
export BPY_BRIDGE_HOME=/run/user/1000/bpy-bridge     # POSIX
$env:BPY_BRIDGE_HOME = "C:\Users\you\bpy-bridge"     # PowerShell
```

文件内容就是 token 加一个换行。读取时会去掉空白，所以手工编辑它是安全的。

### 它是怎么生成的

`secrets.token_urlsafe(32)` —— 来自操作系统 CSPRNG 的 256 位，渲染成 43 个 URL 安全字符。**只生成一次**，首次启动时，之后复用。

POSIX 上文件以 `0600` 权限写入。Windows 上 `chmod` 只切换只读位，所以真正的保护来自文件位于用户配置目录内，而该目录默认受 ACL 限制。详见 [security.md](security.md)。

### 查看与轮换

```bash
bpy-bridge token-path        # 客户端去哪里找
bpy-bridge token             # 打印 token 本身
```

轮换方法：删掉文件，重启桥接。下次启动会生成新 token；客户端在每次构造时都读文件，所以无需改配置就会用上新值。

```bash
rm ~/.bpy-bridge/token        # POSIX
Remove-Item ~/.bpy-bridge/token   # PowerShell
```

### 为什么显式传入的 token 仍然会落盘

如果你传了 `token="..."`，它默认会被**持久化**。这是刻意的：客户端是通过那个文件发现 token 的，所以一个用显式 token 启动、却只把 token 留在内存里的服务，对所有遵循文档流程的客户端来说都是不可达的。想关掉就传 `persist_token=False`。

---

## 网络设置

### 端口

```python
server.start(port=9999)
```

```bash
bpy-bridge --port 9999 ping
```

POSIX 上低于 1024 的端口需要提权。挑一个空闲端口就行；`9876` 是默认值，示例都假设它。

如果端口已被占用，`start()` 会抛 `OSError`（`EADDRINUSE`）。查一下是谁占着：

```bash
netstat -ano | findstr 9876      # Windows
lsof -i :9876                    # POSIX
```

### 绑定非回环地址

你几乎肯定不该这么做。这个服务会以你的权限执行任意 Python。

```python
# 除非你确实要这么做，否则会抛 ValueError：
server.start(host="0.0.0.0", allow_remote=True)
```

要求显式写 `allow_remote=True`，是为了让这个决定在代码审查中可见，而不是藏在某个配置值里。只要 `--host` 不是回环地址，CLI 就会往 stderr 打警告：

```
bpy-bridge: warning: 10.0.0.5 is not a loopback address; the code you send runs
with your user's privileges on that host.
```

`is_loopback()` 接受 `127.0.0.0/8`、`::1`，以及常见的 `localhost` 别名。它无法分类的主机名会被当作**非**回环处理，所以失败模式是「拒绝启动」，而不是「悄悄暴露」。

---

## 限制与超时

### 请求超时

每个请求都带一个预算。服务端等待主线程取走任务的时间达到该预算后，返回 `kind: "timeout"`。

| 层 | 默认 | 如何修改 |
|---|---|---|
| 客户端 socket 读取 | 请求超时 + 30 秒 | 自动 |
| 单请求预算 | `600` 秒 | `--timeout` / `BridgeClient(timeout=...)` / 每次调用 |
| 服务端兜底 | `600` 秒 | `DEFAULT_TIMEOUT` |

```bash
bpy-bridge exec --file build_scene.py --timeout 1800
```

```python
bridge.exec("long_job()", timeout=1800)
```

> **超时不会取消任何东西。** Python 无法安全地中断一个正在执行的栈帧，所以任务会继续在 Blender 的
> 主线程上跑。超时停止的是**你**的等待，不是活儿本身。这一点必须说清楚，因为它是人们最容易误解的那个限制。

### 帧大小

请求和响应都被限制在 4 MiB。没有这个上限，Blender 里一个 `while True: print(...)` 会把 socket 缓冲区塞满，两端一起永久阻塞。有了它，服务端会返回 `kind: "protocol"` 然后关闭连接。

如果你确实需要往回送大块输出，可以调大：

```python
server.start(max_frame_bytes=16 * 1024 * 1024)
```

注意：在慢速回环连接上设置很大的上限，意味着长时间停顿，而不是快速传输。

### 泵吞吐

主线程泵每个 tick 最多处理 `_PUMP_BATCH`（8）个排队任务，每 `_PUMP_INTERVAL`（0.02 秒）一次。这是一个刻意折中：一个 tick 排空队列会让 UI 卡顿，一个 tick 只处理一个又会让批处理慢得像爬。这些是模块常量，不是构造参数 —— 只有在你**测量**出问题之后才去改：

```python
import bpy_bridge.server as server_module
server_module._PUMP_BATCH = 16
```

---

## CLI 参考

```
bpy-bridge [全局选项] <命令> [命令选项]
```

全局选项在命令动词**之前或之后**都可以：

```bash
bpy-bridge --port 9999 ping      # 等价
bpy-bridge ping --port 9999
```

### 全局选项

| 选项 | 默认 | 含义 |
|---|---|---|
| `--host HOST` | `127.0.0.1` | 桥接主机。 |
| `--port PORT` | `9876` | 桥接端口。 |
| `--token TOKEN` | 从 token 文件读 | 内联指定共享密钥。 |
| `--token-file PATH` | `~/.bpy-bridge/token` | 要读取的 token 文件。 |
| `--timeout SECONDS` | `600` | 单请求预算。 |
| `--json` | 关 | 在 stdout 上只输出一个 JSON 对象。 |
| `--version` | — | 打印版本和协议，退出码 `0`。 |

### 命令

| 命令 | 作用 |
|---|---|
| `ping` | 检查 Blender 是否在监听、token 是否有效。打印 `pong  host:port`。 |
| `status` | 打印场景、版本、相机、对象数，以及集合预览。 |
| `exec [CODE]` | 在 Blender 内求值 `CODE`。 |
| `exec --file PATH` | 在 Blender 内执行本地 `.py` 文件。 |
| `shot PATH` | 把 Blender 窗口截图到 `PATH`。需要 GUI 会话。 |
| `token-path` | 打印客户端去哪里找 token。 |
| `token` | 打印 token 本身。 |

### `exec` 选项

| 选项 | 含义 |
|---|---|
| `--file PATH`、`-f PATH` | 运行本地文件而不是内联代码。与内联代码互斥。 |
| `--quiet`、`-q` | 抑制 stdout 和结果，只打印错误。 |

### `--json` 信封

成功：

```json
{"ok": true, "kind": "ok", "result": "5757", "stdout": "", "error": "", "duration_ms": 0.27, "source": "<argv>"}
```

失败：

```json
{"ok": false, "kind": "error", "error": "cannot reach Blender bridge ...", "exit": 3}
```

`kind` 是机器可读的结果。按它分支，永远不要按 `error` 文本分支。

### 读取结构化数据

`result` 是末尾表达式的 `repr`，**不是**可解析的 JSON。给机器消费时，用 `print` 输出 JSON，然后读 `stdout`：

```python
# 脚本里
print(json.dumps(payload))
```

```bash
bpy-bridge exec --file report.py --json | python -c "import json,sys; print(json.load(sys.stdin)['stdout'])"
```

---

## Python 客户端参考

```python
from bpy_bridge import BridgeClient

bridge = BridgeClient(
    host="127.0.0.1",
    port=9876,
    token=None,          # None -> 从 token 文件读
    token_path=None,     # None -> ~/.bpy-bridge/token
    timeout=600.0,
)
```

创建客户端很廉价且无副作用；在第一次调用之前不会建立连接。连接不做池化 —— 每个连接承载一个请求，与服务端一致。

| 方法 | 返回 | 说明 |
|---|---|---|
| `ping()` | `True` | token 错误时抛 `BridgeAuthError`。 |
| `status()` | `dict` | 走专用的 `status` 操作，所以载荷是真正的 JSON。 |
| `exec(code, timeout=None)` | `ExecResult` | 远程异常不会让它抛错；检查 `ok`/`kind`。 |
| `exec_or_raise(code, timeout=None)` | `str` | 失败时抛异常。批处理里用它。 |
| `run_file(path, timeout=None)` | `ExecResult` | 在 Blender 内执行本地 `.py`。 |
| `screenshot(path, timeout=None)` | `ExecResult` | 让 Blender 给自己的窗口截图。 |
| `BridgeClient.from_token_file(path)` | `BridgeClient` | 便利构造函数。 |

`ExecResult` 携带 `ok`、`kind`、`result`、`stdout`、`error`、`duration_ms` 和 `request_id`。当 `ok` 为 `False` 时它是假值；`result.raise_for_status()` 会抛出对应的异常子类。

```python
result = bridge.exec("1 / 0")
print(result.ok)      # False
print(result.kind)    # 'exec'
print(result.error)   # 真实 traceback，在 Blender 内部渲染
```

---

## 退出码

| 码 | 含义 | 典型原因 |
|---|---|---|
| `0` | 成功 | — |
| `1` | 代码在 Blender 里运行并抛了异常 | 你的脚本有 bug |
| `2` | 用法错误 | 参数不对、`--file` 读不到、没给代码 |
| `3` | 连不上 Blender | 没在运行、端口不对、桥接没启动 |
| `4` | token 被拒绝 | 客户端和服务端读的是不同 token 文件 |
| `5` | 超时 | 任务在预算内没被取走 |

`--json` 模式下的失败也会带上 `"exit": <code>`，所以调用方永远不需要按 stderr 文本分支。

---

## 自启动

Blender 启动时会执行 `scripts/startup/` 目录里的每一个 `.py`。把这个放进去，桥接就一直在：

```python
# bpy_bridge_startup.py
import os
import traceback

SERVER = os.path.expanduser("~/tools/bpy-bridge/bpy_bridge/server.py")

try:
    with open(SERVER, "r", encoding="utf-8") as handle:
        source = handle.read()
    exec(compile(source, SERVER, "exec"), {"__name__": "__bpy_bridge_startup__"})
except Exception:
    # 绝不能让桥接拖垮 Blender 的启动：在这里抛异常会让 Blender 处于半初始化状态。
    traceback.print_exc()
    print("[bpy-bridge] autostart failed; continuing without the bridge")
```

各操作系统配置目录：

| 系统 | 路径 |
|---|---|
| Linux | `~/.config/blender/<version>/scripts/startup/` |
| macOS | `~/Library/Application Support/Blender/<version>/scripts/startup/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\<version>\scripts\startup\` |

如果启动时要换端口，别依赖文件的 `__main__` 块，显式调用 `start()`：

```python
exec(compile(source, SERVER, "exec"), namespace)
namespace["start"](port=9999)
```

---

## 按症状排查

### `cannot reach Blender bridge`（退出码 3）

按可能性排序：

1. 桥接没在**这个** Blender 实例里运行。在控制台里启动它。
2. Blender 以另一个用户身份运行，于是它把 token 写到了另一个 home 目录。
3. 端口被别的进程占了 —— 用 `netstat`/`lsof` 查。
4. 防火墙拦了回环（少见，但在锁死的企业机器上会发生）。

### `bad token`（退出码 4）

客户端和服务端对 token 文件的认识不一致。对比：

```bash
bpy-bridge token-path        # 客户端读的是哪个
```

和 Blender 启动时打印的 `token file:` 那一行。对不上通常意味着不同用户，或者只给一侧设了 `BPY_BRIDGE_HOME`。

### `timeout`（退出码 5）

主线程始终没取走任务。常见原因：

- Blender 正忙于某个模态操作（文件对话框会阻塞 timer）。
- 上一个任务还在跑，占着主线程。
- 桥接启动了但 `bpy.app.timers` 没在触发 —— 检查 Blender 是否处于暂停 timer 的状态。

### 你的代码里出现 `NameError` 或 `AttributeError`

那是你的脚本，不是桥接。traceback 是 Blender 内部的真实那一份，所以行号可信。变量会跨请求持久化；来自早先请求的陈旧名字是最常见的意外：

```bash
bpy-bridge exec "count"    # 只要之前的请求赋过值，就能用
```

### 输出巨大或被截断

帧上限是 4 MiB。要么少打印点，要么调大 `max_frame_bytes`。注意超过上限会得到 `kind: "protocol"`，而不是被截断的结果 —— 响应是被拒绝的，不是悄悄砍掉的。
