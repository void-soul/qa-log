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
BACKUP_NAME = "bak-agentlog"


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


def hook_entry():
    """构造一条 hook 配置（command 指向同目录的 agent_log_hook.py）。"""
    # 统一用正斜杠：JSON 与 Git Bash 都友好
    script = HOOK_SCRIPT.replace("\\", "/")
    return [{
        "hooks": [{
            "type": "command",
            "command": f'python "{script}"',
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
    # 再写入/更新需要的两个事件
    for ev in EVENTS:
        if is_ours(cfg, ev):
            hooks[ev] = hook_entry()  # 更新（脚本路径可能变化）
            changed.append(f"{ev}（更新）")
        else:
            hooks[ev] = hook_entry()
            changed.append(f"{ev}（新增）")

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
        if is_ours(cfg, ev):
            hooks.pop(ev, None)
            removed.append(ev)
    if not removed:
        print("未发现本脚本注册的 hooks，未做改动。")
        return
    if not hooks:
        cfg.pop("hooks", None)  # 空的 hooks 段一并移除
    save_settings(cfg)
    print(f"✅ 已从 {SETTINGS} 移除: {', '.join(removed)}")
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
