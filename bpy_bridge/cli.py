# -*- coding: utf-8 -*-
"""Command line interface: ``bpy-bridge <command>``.

Design notes:

* Exit codes are stable and documented, because CI and shell scripts depend on
  them. ``0`` success, ``1`` remote code raised, ``2`` usage error, ``3``
  cannot reach Blender, ``4`` bad token, ``5`` timed out.
* ``--json`` exists so the CLI can be a subprocess target for tools that do not
  speak Python, including LLM agent frameworks.
* Nothing prints the token. It is read from disk; ``token path`` is the only
  command that mentions where it lives.
"""

import argparse
import json
import os
import sys

from . import __version__, protocol
from .client import BridgeClient
from .protocol import (
    BridgeAuthError,
    BridgeError,
    BridgeTimeout,
    BridgeUnreachable,
    ProtocolError,
    RemoteExecError,
)
from .server import default_token_path, is_loopback

EXIT_OK = 0
EXIT_REMOTE = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_AUTH = 4
EXIT_TIMEOUT = 5

_EXIT_FOR_ERROR = (
    (BridgeUnreachable, EXIT_UNREACHABLE),
    (BridgeAuthError, EXIT_AUTH),
    (BridgeTimeout, EXIT_TIMEOUT),
    (RemoteExecError, EXIT_REMOTE),
    (ProtocolError, EXIT_REMOTE),
)

#: Maps a response ``kind`` straight to an exit code, for paths that hold an
#: ExecResult rather than an exception.
_EXIT_FOR_KIND = {
    protocol.KIND_AUTH: EXIT_AUTH,
    protocol.KIND_TIMEOUT: EXIT_TIMEOUT,
    protocol.KIND_EXEC: EXIT_REMOTE,
    protocol.KIND_PROTOCOL: EXIT_REMOTE,
    protocol.KIND_INTERNAL: EXIT_REMOTE,
}


def _add_connection_options(parser, suppress_defaults):
    """Attach the options that describe *how to reach* Blender.

    ``suppress_defaults`` is set for the subcommands: the top-level parser
    already filled those attributes, and a subparser default would silently
    clobber a value the user passed *before* the subcommand
    (``bpy-bridge --port 9000 ping``). Suppressing the default makes the
    subparser only override when the flag is genuinely given after the
    subcommand. That is the whole trick to letting global flags appear on
    either side of the verb.
    """
    def _default(value):
        return argparse.SUPPRESS if suppress_defaults else value

    parser.add_argument("--host", default=_default(protocol.DEFAULT_HOST),
                        help="bridge host (default: %s)" % protocol.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_default(protocol.DEFAULT_PORT),
                        help="bridge port (default: %d)" % protocol.DEFAULT_PORT)
    parser.add_argument("--token", default=_default(None),
                        help="shared token (default: read from the token file)")
    parser.add_argument("--token-file", default=_default(None),
                        help="token file (default: %s)" % default_token_path())
    parser.add_argument("--timeout", type=float, default=_default(protocol.DEFAULT_TIMEOUT),
                        help="per-request budget in seconds (default: %g)"
                             % protocol.DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true",
                        default=_default(False),
                        help="emit a single JSON object on stdout")
    parser.add_argument("--version", action="version",
                        version="bpy-bridge %s (protocol v%d)"
                                % (__version__, protocol.PROTOCOL_VERSION),
                        help="print the version and exit")
    return parser


def build_parser():
    parser = argparse.ArgumentParser(
        prog="bpy-bridge",
        description="Drive a running Blender from the command line.",
        epilog="Examples:\n"
               "  bpy-bridge ping\n"
               "  bpy-bridge exec 'len(bpy.data.objects)'\n"
               "  bpy-bridge exec --file build_scene.py --timeout 900\n"
               "  bpy-bridge status --json\n"
               "  bpy-bridge shot ui.png\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_connection_options(parser, suppress_defaults=False)

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def _sub(name, help_text):
        # parents=[] plus the explicit call below keeps the flags documented in
        # `bpy-bridge exec --help` as well as accepted after the verb.
        child = sub.add_parser(name, help=help_text)
        _add_connection_options(child, suppress_defaults=True)
        return child

    _sub("ping", "check that Blender is listening and the token is valid")
    _sub("status", "print scene / version / camera information")

    exec_parser = _sub("exec", "run Python code inside Blender")
    source = exec_parser.add_mutually_exclusive_group()
    source.add_argument("code", nargs="?", help="Python source to evaluate")
    source.add_argument("--file", "-f", dest="path", help="execute a local .py file")
    exec_parser.add_argument("--quiet", "-q", action="store_true",
                             help="print only the result, not stdout/errors")

    shot_parser = _sub("shot", "screenshot the Blender window")
    shot_parser.add_argument("path", help="output PNG path")

    _sub("token-path", "print where the shared token file lives")
    _sub("token", "print the shared token (for scripts that need it)")
    return parser


def _client(args):
    return BridgeClient(
        host=args.host,
        port=args.port,
        token=args.token,
        token_path=args.token_file,
        timeout=args.timeout,
    )


def _emit_json(payload, stream=None):
    stream = stream or sys.stdout
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stream.flush()


def _fail(exc, args, extra=None):
    code = EXIT_REMOTE
    for error_type, exit_code in _EXIT_FOR_ERROR:
        if isinstance(exc, error_type):
            code = exit_code
            break
    if args.json:
        payload = {"ok": False, "kind": "error", "error": str(exc), "exit": code}
        if extra:
            payload.update(extra)
        _emit_json(payload, sys.stdout)
    else:
        sys.stderr.write("bpy-bridge: %s\n" % exc)
    return code


def _warn_if_remote(host):
    if not is_loopback(host):
        sys.stderr.write(
            "bpy-bridge: warning: %s is not a loopback address; the code you send "
            "runs with your user's privileges on that host.\n" % host
        )


# ------------------------------------------------------------------- commands
def cmd_ping(args):
    _warn_if_remote(args.host)
    client = _client(args)
    client.ping()
    if args.json:
        _emit_json({"ok": True, "kind": "ok", "host": args.host, "port": args.port})
    else:
        print("pong  %s:%d" % (args.host, args.port))
    return EXIT_OK


def cmd_status(args):
    _warn_if_remote(args.host)
    info = _client(args).status()
    if args.json:
        _emit_json({"ok": True, "kind": "ok", "status": info})
        return EXIT_OK
    for key in ("blender", "scene", "file", "engine", "objects", "camera", "python", "pid"):
        if key in info:
            print("%-10s %s" % (key + ":", info[key]))
    collections = info.get("collections")
    if collections:
        print("%-10s %s" % ("collections:", ", ".join(collections)))
    return EXIT_OK


def cmd_exec(args):
    _warn_if_remote(args.host)
    if args.path:
        # Read the script *before* touching the network, and report a missing or
        # unreadable file as the usage error it is. Letting the OSError bubble
        # to main() would surface "cannot reach Blender", which is a lie: the
        # user's typo has nothing to do with Blender.
        try:
            with open(args.path, "r", encoding="utf-8") as handle:
                code = handle.read()
        except OSError as exc:
            sys.stderr.write("bpy-bridge: cannot read %s: %s\n" % (args.path, exc))
            return EXIT_USAGE
        label = args.path
    elif args.code:
        code = args.code
        label = "<argv>"
    else:
        sys.stderr.write("bpy-bridge: exec needs code or --file\n")
        return EXIT_USAGE

    result = _client(args).exec(code, timeout=args.timeout)
    if args.json:
        _emit_json({
            "ok": result.ok,
            "kind": result.kind,
            "result": result.result,
            "stdout": result.stdout,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "source": label,
        })
    else:
        if result.stdout and not args.quiet:
            sys.stdout.write(result.stdout)
            if not result.stdout.endswith("\n"):
                sys.stdout.write("\n")
        if result.result is not None and not args.quiet:
            print(result.result)
        if not result.ok and result.error:
            sys.stderr.write(result.error)
            if not result.error.endswith("\n"):
                sys.stderr.write("\n")
    if result.ok:
        return EXIT_OK
    return _EXIT_FOR_KIND.get(result.kind, EXIT_REMOTE)


def _as_error(result):
    """Turn a failed ExecResult into the matching exception, for exit codes."""
    if result.kind == protocol.KIND_AUTH:
        return BridgeAuthError(result.error)
    if result.kind == protocol.KIND_TIMEOUT:
        return BridgeTimeout(result.error)
    if result.kind == protocol.KIND_PROTOCOL:
        return ProtocolError(result.error)
    if result.kind == protocol.KIND_EXEC:
        return RemoteExecError(result.error, result.error, result.stdout)
    return BridgeError(result.error)


def cmd_shot(args):
    _warn_if_remote(args.host)
    result = _client(args).screenshot(args.path)
    if result.ok:
        if args.json:
            _emit_json({"ok": True, "kind": "ok", "path": result.result, "stdout": result.stdout})
        else:
            print(result.result)
        return EXIT_OK
    return _fail(_as_error(result), args)


def cmd_token_path(args):
    path = args.token_file or default_token_path()
    if args.json:
        _emit_json({"ok": True, "kind": "ok", "path": path, "exists": os.path.exists(path)})
    else:
        print(path)
    return EXIT_OK


def cmd_token(args):
    path = args.token_file or default_token_path()
    from .server import read_token

    token = args.token or read_token(path)
    if not token:
        sys.stderr.write("bpy-bridge: no token at %s -- start the bridge inside Blender first\n" % path)
        return EXIT_AUTH
    if args.json:
        _emit_json({"ok": True, "kind": "ok", "token": token, "path": path})
    else:
        print(token)
    return EXIT_OK


_COMMANDS = {
    "ping": cmd_ping,
    "status": cmd_status,
    "exec": cmd_exec,
    "shot": cmd_shot,
    "token-path": cmd_token_path,
    "token": cmd_token,
}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except BridgeUnreachable as exc:
        return _fail(exc, args)
    except BridgeAuthError as exc:
        return _fail(exc, args)
    except BridgeTimeout as exc:
        return _fail(exc, args)
    except RemoteExecError as exc:
        return _fail(exc, args, {"stdout": exc.stdout})
    except ProtocolError as exc:
        return _fail(exc, args)
    except BridgeError as exc:
        return _fail(exc, args)
    except OSError as exc:
        return _fail(BridgeUnreachable(str(exc)), args)


if __name__ == "__main__":
    sys.exit(main())
