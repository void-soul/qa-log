#!/usr/bin/env python3
"""stdin 读取助手 —— 带超时，绝不被「永不 EOF 的管道」永久阻塞。

背景：多个脚本支持"把 JSON 从 stdin 读进来"（Windows GBK 环境下这是传中文的
唯一可靠方式）。但自动读 stdin 有一个经典陷阱：宿主用 `stdin=PIPE` 启动子进程
却不close()/end() 写端时（Node `execFile`、忘记close 的 `subprocess.Popen`、
`docker run -i` 挂在别处），`sys.stdin.read()` 会**永久阻塞**，调用方既拿不到
结果也看不到任何报错。

这里的做法：非 TTY 时开一个 daemon 线程读 stdin，最多等 `timeout` 秒。
拿不到数据就视作"没有 stdin 输入"返回 None —— 调用方照常走命令行参数路径。
代价是「宿主给了空管道」的情况下会多等 `timeout` 秒；交互式终端（TTY）不等待。

超时可通过环境变量 QA_STDIN_TIMEOUT 覆盖（秒，默认 2.0）。
"""
import os
import sys
import threading

DEFAULT_TIMEOUT = 2.0


def _timeout():
    try:
        return max(0.1, float(os.environ.get("QA_STDIN_TIMEOUT", DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def read_text_stdin(timeout=None, stream=None):
    """在超时保护下读取整个 stdin；无内容 / 仍是 TTY / 超时都返回 ''。

    `stream` 仅供测试注入；默认用 sys.stdin。
    """
    stream = stream if stream is not None else getattr(sys, "stdin", None)
    if stream is None:
        return ""
    try:
        if stream.isatty():
            return ""          # 交互式终端：绝不读
    except (ValueError, OSError):
        return ""

    box = {}

    def _read():
        try:
            box["data"] = stream.read()
        except Exception as e:                      # noqa: BLE001 - 读失败等价于无输入
            box["err"] = e

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(_timeout() if timeout is None else timeout)
    if t.is_alive():
        # 宿主还占着 stdin 且没给数据：不能等它，否则永久挂死
        return ""
    if box.get("err") is not None:
        return ""
    data = box.get("data") or ""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    return data.strip()


def read_json_stdin(timeout=None):
    """同上，但返回解析后的 dict/list；非 JSON、空输入、超时一律返回 None。"""
    import json

    raw = read_text_stdin(timeout=timeout)
    if not raw:
        return None
    raw = raw.lstrip("﻿")            # 剥离 PowerShell 管道可能带的 BOM
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None