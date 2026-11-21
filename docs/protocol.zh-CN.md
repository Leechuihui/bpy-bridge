# 线协议，版本 1

[English](protocol.md) | **简体中文**

本文档是规范性的。如果你要用另一种语言写客户端，这就是完整的规范。

## 传输

- 基于 TCP 的 IPv4/IPv6，惯例是 `127.0.0.1:9876`。
- 一条连接承载**恰好一个请求和一个响应**，然后服务端关闭它。
- 两个方向都是 UTF-8 编码的 JSON，一行一个对象，以 `\n` 结尾。没有长度前缀，除了换行符之外没有任何分帧。
- 任一方向的最大帧大小：**4 MiB**（`MAX_FRAME_BYTES`）。

## 请求

```json
{
  "protocol": 1,
  "op": "exec",
  "code": "len(bpy.data.objects)",
  "token": "…",
  "timeout": 600.0,
  "request_id": "3f2a"
}
```

| 字段 | 必需 | 类型 | 说明 |
|---|---|---|---|
| `op` | 否 | string | `exec`（默认）、`ping` 或 `status`。 |
| `code` | `exec` 时必需 | string | Python 源码，按 Python REPL 语义求值：语句会执行，末尾表达式的值以 `repr` 返回。末尾表达式求值为 `None` 时返回 `null`。 |
| `token` | 是 | string | 共享密钥。为空或错误 → `kind: "auth"`。 |
| `timeout` | 否 | number | 服务端等待主线程的秒数。默认 `600`。非正数或无法解析的值回退到默认值。 |
| `request_id` | 否 | string | 会在响应里原样回传。用来做请求关联。 |
| `protocol` | 否 | integer | 当前为 `1`。 |

`ping` 和 `status` 的 `code` 可以是 `""`。

## 响应

```json
{
  "protocol": 1,
  "ok": true,
  "kind": "ok",
  "result": "1886",
  "stdout": "",
  "error": "",
  "duration_ms": 0.412,
  "request_id": "3f2a"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | boolean | 永远等于 `kind == "ok"`。 |
| `kind` | string | 机器可读的结果，见下。 |
| `result` | string \| null | `exec`：末尾表达式值的 Python `repr()`；没有末尾表达式、或它求值为 `None` 时为 `null`。`ping`：`"pong"`。`status`：一个 JSON **字符串**，解析后得到状态对象。 |
| `stdout` | string | 代码写到 `sys.stdout` 或 `sys.stderr` 的全部内容，按写入顺序交错排列。 |
| `error` | string | traceback 或消息。成功时为空。 |
| `duration_ms` | number | 花在主线程上的墙钟时间，保留 3 位小数。 |
| `request_id` | string | 仅当请求提供了它才出现。 |

### `kind` 取值

| `kind` | `ok` | 含义 |
|---|---|---|
| `ok` | true | 成功。 |
| `auth` | false | token 缺失或错误。请求没有被执行。 |
| `timeout` | false | 主线程在 `timeout` 秒内没有取走任务。**代码可能仍在运行。** |
| `exec` | false | 代码运行并抛了异常。`error` 里是 traceback。 |
| `protocol` | false | 请求格式错误：JSON 坏了、`op` 未知、帧过大。 |
| `internal` | false | 桥接自身失败（例如没有主线程泵）。 |

客户端应当按 `kind` 分支，永远不要按 `error` 文本分支。

## `result` 是 repr，不是 JSON

这一点坑了很多人，所以值得说两遍。对 `exec`，服务端做的是：

```python
repr(eval(compiled, namespace))
```

所以 `1 + 1` 得到字符串 `"2"`，`"hi"` 得到 `"'hi'"`（带引号），一个 dict 得到 `"{'a': 1}"` —— 它**不是**合法 JSON。如果你需要结构化数据，就自己返回一个 JSON 字符串：

```python
import json; json.dumps({"objects": len(bpy.data.objects)})
```

然后在客户端解析它。`status` 操作已经替你做了这件事。

## 命名空间持久化

每条连接拿到的是全新的传输状态，但执行命名空间是共享的、在桥接的整个生命周期内持久存在。你赋的值会一直在：

```
exec: "counter = 0"      → result null
exec: "counter += 1"     → result null
exec: "counter"          → result "1"
```

命名空间里总是包含：

- `__name__` = `"__bpy_bridge__"`
- `bridge` —— 一个辅助对象（见下）
- `bpy` —— 真实模块，在首次执行时、当它可以被 import 时注入
  （也就是在 Blender 里总是有）。在 Blender 之外它是缺失的，而不是被伪造一个。

## `bridge` 辅助对象

在执行命名空间里，`bridge` 暴露：

| 成员 | 说明 |
|---|---|
| `bridge.bpy` | 真实的 `bpy` 模块。 |
| `bridge.status()` | 一个 dict，含 `blender`、`scene`、`file`、`engine`、`objects`、`camera`、`collections`、`python`、`pid`。 |
| `bridge.shot(path)` | 把 Blender 窗口截图到 `path`。返回绝对路径。 |
| `bridge.exec_file(path)` | 在同一个持久命名空间里执行本地 `.py` 文件。 |

## 写一个客户端

最小可用的 Python 客户端大约二十行：

```python
import json, socket

def call(code, token, host="127.0.0.1", port=9876, timeout=600):
    with socket.create_connection((host, port), timeout=timeout + 30) as sock:
        sock.sendall((json.dumps({
            "op": "exec", "code": code, "token": token, "timeout": timeout,
        }) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8"))
```

记得把 socket 读取超时设成至少「请求 `timeout` + 一点余量」；否则一次慢渲染看起来就像连接断了。

## 版本策略

`protocol` 是 `1`。未来的不兼容改动会把它提到 `2`，并且服务端会至少在一个小版本内同时接受两者。新增一个 `op` **不**算破坏性变更；未知的 `op` 本来就会返回 `kind: "protocol"`。
