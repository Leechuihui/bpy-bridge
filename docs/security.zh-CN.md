# 安全模型

[English](security.md) | **简体中文**

`bpy-bridge` 会在你的 Blender 里、以你的用户权限、在你的机器上执行任意 Python。这就是它的全部功能。下面所有内容，都是关于如何确保它**只**为你这么做。

## 威胁模型

**在范围内。** 同一台机器上的另一个进程 —— 或者通过本地网络请求的浏览器页面 —— 未经授权访问到桥接，并以你的用户身份执行代码。这是现实存在的风险，默认值就是围绕它设计的。

**不在范围内。** 一个已经能读到你的 token 文件、能以你的用户身份运行代码、或者能挂调试器的攻击者。到了那一步，桥接已经不是你的问题了。

## 控制措施

### 绑定地址

服务端默认绑定 `127.0.0.1`。`BridgeServer(host="0.0.0.0")` 会在任何 socket 被创建之前就抛 `ValueError`。绑定到别处需要显式的 `allow_remote=True` 标志，它存在的意义是让这个决定在代码审查中可见，而不是藏在某个配置文件里。

只要 `--host` 不是回环地址，CLI 就会往 stderr 打警告：

```
bpy-bridge: warning: 10.0.0.5 is not a loopback address; the code you send runs
with your user's privileges on that host.
```

`is_loopback()` 通过 `ipaddress.ip_address(...).is_loopback` 分类，再加上常见的 `localhost` 别名。它无法解析的主机名会被当作**非**回环处理，所以失败模式是「拒绝启动」，而不是「悄悄暴露」。

### Token

- 用 `secrets.token_urlsafe(32)` 生成 —— 来自操作系统 CSPRNG 的 256 位。
- 存储在 `~/.bpy-bridge/token`（用 `BPY_BRIDGE_HOME` 覆盖）。
- POSIX 上以 `chmod 0600` 写入。Windows 上 `chmod` 只切换只读位；那里真正的保护来自文件位于用户配置目录内，而该目录默认受 ACL 限制。如果你需要更多保护，把文件放到其他用户无法穿越的目录里。
- 用 `secrets.compare_digest` 比较，两侧都按字节编码，这样一个非 ASCII token 不会在认证路径里抛 `TypeError` 而意外 fail open。（它本来也不会 fail open —— 异常会产生一个错误响应 —— 但认证路径里崩溃仍然是错误的形状。）
- 从不记录日志，CLI 也从不在 `bpy-bridge token` 子命令之外打印它。

轮换 token 的方法是删掉文件并重启桥接。客户端在每次构造时都从磁盘读取，所以会自动用上新值。

### 帧大小

请求和响应都被限制在 4 MiB。没有这个上限，Blender 里一个 `while True: print(...)` 会把 socket 缓冲区塞满，两端互相永久等待。有了它，服务端会回复 `kind: "protocol"` 然后关闭。

### 超时

每个请求都带一个预算。服务端以该超时阻塞在一个 `threading.Event` 上；如果主线程始终没取走任务，就返回 `kind: "timeout"`。客户端把自己的 socket 读取超时设为「请求超时 + 30 秒」，这样一次合理的慢渲染不会被误认为连接断开。

## 它不防什么

- **你自己发过去的代码。** 没有沙箱、没有 import 白名单、没有文件系统牢笼。如果你发 `import os; os.remove(...)`，它就会删。这就是交易本身。
- **取消。** Python 无法安全地中断一个正在运行的栈帧。一个超时的任务会继续在 Blender 主线程上跑；超时只是停止**你**的等待。
- **任何拿到你 token 文件的人。** 读到那个文件，等价于完整的代码执行能力。把它当 SSH 私钥对待。
- **Blender 自带的插件。** 代码和你安装的每一个插件跑在同一个解释器里，共享它们留下的任何全局变量。

## 在共享机器上运行

如果其他用户共用这台主机，回环地址不构成边界 —— 任何本地用户都能连到 `127.0.0.1`。token 是唯一的边界，所以：

1. 确认 token 文件的权限确实排除了其他用户。POSIX 上 `ls -l ~/.bpy-bridge/token` 应当显示 `-rw-------`。
2. 优先使用位于任何共享目录之外的、按用户隔离的 `BPY_BRIDGE_HOME`。
3. 任何你不太确定的会话之后，轮换 token。

## 报告

如果你发现绕过回环检查或 token 检查的方法，请在仓库上开一个私密的安全公告，而不是公开 issue。
