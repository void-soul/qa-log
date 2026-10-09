#!/usr/bin/env python3
"""
一键配置 CodeBuddy hooks（新用户友好）。

作用
----
把 agent_log_hook.py 注册进 `~/.codebuddy/settings.json` 的 hooks，
使得 CodeBuddy（IDE / CLI）在会话中自动把「用户消息」和「Agent 回复」
追加写入当前项目根目录的 qa.db。

用法
----
  python setup_hooks.py            # 安装/更新 hooks（幂等，自动备份）
  python setup_hooks.py --status   # 查看当前配置状态
  python setup_hooks.py --remove   # 移除本脚本注册的 hooks

说明
----
- 只增删 UserPromptSubmit 与 Stop 两个事件，不碰 settings.json 的其他内容。
- 首次安装会备份原文件为 settings.json.bak-agentlog（若已存在则跳过备份）。
- 安装后需重启 CodeBuddy（或在 /hooks 面板审核应用）才会生效。
"""

import argparse
import json
import os
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SETTINGS = os.path.join(os.path.expanduser("~"), ".codebuddy", "settings.json")
HOOK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_log_hook.py")
BACKUP = SETTINGS + ".bak-agentlog"
EVENTS = ("UserPromptSubmit", "Stop")


def load_settings():
    """读取 settings.json；不存在时返回空骨架。"""
    if not os.path.isfile(SETTINGS):
        return {}
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ {SETTINGS} 不是有效 JSON：{e}", file=sys.stderr)
        print("   请先修复该文件（或从备份恢复）再运行本脚本。", file=sys.stderr)
        sys.exit(1)


def save_settings(cfg):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def python_cmd():
    """hook 里的解释器：优先 `python`，本机只有官方 `py -3` 时回退（写死 python 会静默失效）。"""
    import shutil
    return "python" if shutil.which("python") else "py -3"


def hook_entry():
    """构造一条 hook 配置（command 指向同目录的 agent_log_hook.py）。"""
    # 统一用正斜杠：JSON 与 Git Bash 都友好
    script = HOOK_SCRIPT.replace("\\", "/")
    return [{
        "hooks": [{
            "type": "command",
            "command": f'{python_cmd()} "{script}"',
            "timeout": 30,
        }]
    }]


def is_ours(cfg, event):
    """判断某事件的 hooks 是否已由本脚本注册（按 command 里的脚本路径判断）。"""
    for grp in cfg.get("hooks", {}).get(event, []):
        for h in grp.get("hooks", []):
            if "agent_log_hook.py" in str(h.get("command", "")):
                return True
    return False


def strip_ours(groups):
    """只摘掉本脚本注册的 group，**保留用户自己挂在同一事件上的 hook**。

    绝不能 `hooks[ev] = hook_entry()` 整体覆盖：那会把用户自己的 hook 静默删掉
    （启用/停用一次即永久丢失，且首次安装的备份无法回滚后续覆盖）。
    """
    return [g for g in (groups or [])
            if not any("agent_log_hook.py" in str(h.get("command", ""))
                       for h in (g.get("hooks") or []))]


def do_install():
    if not os.path.isfile(HOOK_SCRIPT):
        print(f"❌ 找不到 hook 脚本：{HOOK_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    cfg = load_settings()

    # 备份（仅首次）
    if os.path.isfile(SETTINGS) and not os.path.isfile(BACKUP):
        shutil.copy2(SETTINGS, BACKUP)
        print(f"已备份原配置 → {BACKUP}")

    hooks = cfg.setdefault("hooks", {})
    changed = []
    # 先清理：本脚本之前注册的、但现在不再需要的事件
    for ev in list(hooks.keys()):
        if ev not in EVENTS and is_ours(cfg, ev):
            hooks.pop(ev, None)
            changed.append(f"{ev}（移除，不再需要）")
    # 再写入/更新需要的两个事件：只替换自己那一条，用户自己的 group 原样保留
    for ev in EVENTS:
        before = hooks.get(ev) or []
        ours = strip_ours(before)
        had_ours = len(ours) != len(before)
        hooks[ev] = ours + hook_entry()
        changed.append(f"{ev}（{'更新' if had_ours else '新增'}）")

    save_settings(cfg)
    print(f"✅ 已写入 {SETTINGS}")
    for c in changed:
        print(f"   - hooks.{c}")
    print(f"   hook 脚本: {HOOK_SCRIPT}")
    print("\n下一步：重启 CodeBuddy（或在 /hooks 面板审核应用）后生效。")
    print("之后正常对话即会自动把「用户消息 / Agent 回复」写入项目根目录的 qa.db。")


def do_remove():
    cfg = load_settings()
    hooks = cfg.get("hooks")
    if not hooks:
        print("settings.json 中没有 hooks 配置，无需移除。")
        return
    removed = []
    for ev in EVENTS:
        before = hooks.get(ev) or []
        ours = strip_ours(before)
        if len(ours) == len(before):
            continue                      # 本脚本没在这个事件上注册过，不碰
        kept = ours                        # 用户自己的 hook 必须保留
        if kept:
            hooks[ev] = kept
        else:
            hooks.pop(ev, None)
        removed.append(ev)
    if not removed:
        print("未发现本脚本注册的 hooks，未做改动。")
        return
    if not hooks:
        cfg.pop("hooks", None)  # 空的 hooks 段一并移除
    save_settings(cfg)
    print(f"✅ 已从 {SETTINGS} 移除: {', '.join(removed)}（你自己挂在这些事件上的 hook 已保留）")
    print("重启 CodeBuddy 后生效。")


def do_status():
    print(f"settings.json: {SETTINGS} {'✅存在' if os.path.isfile(SETTINGS) else '❌不存在'}")
    print(f"hook 脚本:     {HOOK_SCRIPT} {'✅存在' if os.path.isfile(HOOK_SCRIPT) else '❌不存在'}")
    print(f"备份文件:      {BACKUP} {'存在' if os.path.isfile(BACKUP) else '无'}")
    cfg = load_settings()
    hooks = cfg.get("hooks") or {}
    print()
    if not hooks:
        print("当前未配置任何 hooks。运行 `python setup_hooks.py` 安装。")
        return
    for ev in sorted(hooks.keys()):
        ours = "✓" if is_ours(cfg, ev) else " "
        cmds = [h.get("command", "") for grp in hooks[ev] for h in grp.get("hooks", [])]
        print(f"  [{ours}] {ev}: {cmds[0][:100] if cmds else '(空)'}")
    print("\n说明：[✓] 表示由本脚本注册的事件。")
    print("提示：UserPromptSubmit / Stop 带有 [✓] 即为已安装；修改配置后需重启 CodeBuddy 生效。")


def main():
    p = argparse.ArgumentParser(description="一键配置 CodeBuddy agent 日志 hooks")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true", help="查看当前配置状态")
    g.add_argument("--remove", action="store_true", help="移除本脚本注册的 hooks")
    a = p.parse_args()

    if a.status:
        do_status()
    elif a.remove:
        do_remove()
    else:
        do_install()


if __name__ == "__main__":
    main()
