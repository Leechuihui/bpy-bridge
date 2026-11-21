# 安装桥接，让它一直在

[English](install.md) | **简体中文**

两种方式，取决于你愿意花多少心思。

## 方案 A —— 一行命令（免安装）

在 Blender 的 Python 控制台里（`Shift+F4`）：

```python
exec(compile(open(r"/path/to/server.py", encoding="utf-8").read(),
             "bpy_bridge_server", "exec"))
```

如果你只是试用，或者想精确控制桥接什么时候开始监听，这是推荐路径。`server.py` 没有任何标准库以外的 import，所以单个文件就是一次完整安装。

## 方案 B —— 每次启动 Blender 自动拉起

Blender 启动时会执行 `scripts/startup/` 目录里的每一个 `.py` 文件。往那儿丢一个小文件，桥接就跟着 Blender 一起起来。

找到你的配置目录：

| 系统 | 路径 |
|---|---|
| Linux | `~/.config/blender/<version>/scripts/startup/` |
| macOS | `~/Library/Application Support/Blender/<version>/scripts/startup/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\<version>\scripts\startup\` |

在里面创建 `bpy_bridge_startup.py`：

```python
# ~/.config/blender/4.2/scripts/startup/bpy_bridge_startup.py
import os
import traceback

SERVER = os.path.expanduser("~/tools/bpy-bridge/bpy_bridge/server.py")

try:
    with open(SERVER, "r", encoding="utf-8") as handle:
        source = handle.read()
    exec(compile(source, SERVER, "exec"), {"__name__": "__bpy_bridge_startup__"})
except Exception:
    # 绝不能让桥接拖垮 Blender 的启动：一个在这里抛异常的自启文件
    # 会让 Blender 处于半初始化状态。
    traceback.print_exc()
    print("[bpy-bridge] autostart failed; continuing without the bridge")
```

重启 Blender。你应该能在系统控制台里看到 `[bpy-bridge] listening on ...` 那一行。

> **关于路径。** `~` 由 `os.path.expanduser` 展开，所以只要把 server 放在固定的相对位置，
> 同一个文件在三个平台上都能用。Windows 上用原始字符串或正斜杠，避免 `\U` 转义带来的意外。

## 验证

```bash
bpy-bridge ping
```

`pong  127.0.0.1:9876` 表示一切都接好了。

如果它说 `cannot reach Blender bridge`，按可能性排序：

1. 桥接没在**这个** Blender 实例里运行（在控制台里启动它）。
2. Blender 以另一个用户身份运行，于是它把 token 写到了另一个 home 目录。
3. 端口 9876 被别的进程占了。用 `netstat -ano | findstr 9876`（Windows）或
   `lsof -i :9876`（POSIX）查一下。
4. 防火墙拦了回环 —— 这不该发生，但在锁死的企业机器上偶尔会。

如果它说 `bad token`，说明客户端和服务端对 token 文件的认识不一致。`bpy-bridge token-path` 会打印客户端用的路径；把它和服务端启动时打印的 `token file:` 那一行对一下。

## 选择端口

```python
# 在 Blender 里
server = start(port=9999)
```

```bash
bpy-bridge --port 9999 ping
```

POSIX 上低于 1024 的端口需要提权，不值得。

## 卸载

删掉那个自启文件。就这些 —— 没有别的东西被修改。可选地删掉 `~/.bpy-bridge/` 以移除 token。
