# Security policy

`bpy-bridge` runs arbitrary Python inside your Blender, with your user's
privileges. A bypass of the loopback or token check is therefore equivalent to
code execution as you. The full model — what is and is not defended against — is
in [docs/security.md](docs/security.md). This file is the short version and the
reporting procedure.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

The project is pre-1.0. Fixes land on `main` and ship in the next release; there
are no backport branches yet.

## Reporting a vulnerability

**Please do not open a public issue for a security bypass.**

Use GitHub's [private security advisory][advisory] flow. It gives us a private
thread, a place to develop the fix, and a way to credit you.

[advisory]: https://github.com/Leechuihui/bpy-bridge/security/advisories/new

A useful report contains:

- The version of `bpy-bridge` and of Blender.
- The platform, and whether the server was bound to loopback or with
  `allow_remote=True`.
- What an attacker gains — for example "executes code without the token" or
  "reads the token from another local user".
- Steps to reproduce, ideally a minimal script.

If you cannot use the advisory flow, open a normal issue titled
`security: <summary>` and say that details follow privately.

## What to expect

This is a volunteer project, so these are targets rather than guarantees:

- **Acknowledgement** within about a week.
- **An assessment** — whether it is in scope per [docs/security.md](docs/security.md)
  — once reproduced.
- **Credit** in the advisory and the release notes, unless you prefer otherwise.

## Scope

In scope: bypassing the token check, reaching the bridge from off-host when it
was bound to loopback, or leaking the token to another local user.

Out of scope, because they are documented behaviour: code you send runs
unsandboxed; a timed-out job keeps running; anyone who can read your token file
already has your privileges; add-on code shares the interpreter.
