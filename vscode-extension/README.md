# QA Log — VSCode / CodeBuddy 扩展

在侧边栏浏览项目根目录的 `qa.db`，包含两个视图：

| 入口 | 视图 | 数据 |
|------|------|------|
| 🗒️ **QA 记录** | 搜索 / 状态筛选，点击在 IDE 中间区域查看详情（现象、根因、方案、涉及文件） | `qa_entries` 表 |
| 💬 **Agent 日志** | 用户输入历史（时间倒序，单行省略），点击查看全文 | `agent_log` 表 |

两个视图均为：侧边栏单列列表（虚拟滚动）+ 点击在 IDE 中间区域打开详情面板（复用，非弹窗），样式跟随 VSCode 主题。

## 前置条件

1. **Python 3.8+**（在 PATH 中；可用 `qaLog.pythonPath` 指定完整路径）
2. 项目根目录已有 `qa.db`（在该项目首次使用 qa-log skill 时由
   `python <skill>/scripts/qa_tool.py setup` 创建）

## 安装

### 方式一：打包安装（推荐）

```bash
cd vscode-extension
npx --yes @vscode/vsce package --no-dependencies
# 生成 qa-log-browser-0.1.0.vsix
```

然后在 VSCode / CodeBuddy 里：扩展面板 → `...` → **从 VSIX 安装**。

### 方式二：开发调试

```bash
cd vscode-extension
code --extensionDevelopmentPath=$(pwd)   # 或在 CodeBuddy 里打开本目录按 F5
```

## Agent 日志的数据来源（CodeBuddy hooks）

`agent_log` 表由 CodeBuddy 的 hooks 自动追加，**只记录两种内容**：

| 记录 | 事件 | 内容 |
|------|------|------|
| `user_prompt`（用户消息） | `UserPromptSubmit` | 用户发给 Agent 的消息**全文**（`title` 为前 100 字概要） |
| `assistant_reply`（Agent 回复） | `Stop` | Agent 回复。**注意**：回复正文被 CodeBuddy 保护读不到（实测 `ACCESS_DENIED`），记录的是回复完成摘要；若未来版本放开限制则自动记录正文 |

### 新用户配置（一条命令）

在任意目录运行（把 `<skill>` 替换为 qa-log skill 的实际路径）：

```bash
python <skill>/scripts/setup_hooks.py
```

它会：
- 备份 `~/.codebuddy/settings.json`（首次为 `settings.json.bak-agentlog`）
- 注册 `UserPromptSubmit` + `Stop` 两个 hook（幂等，重复运行安全，不碰其他配置）
- 之后正常对话即自动追加日志

常用命令：

```bash
python <skill>/scripts/setup_hooks.py --status   # 查看安装状态
python <skill>/scripts/setup_hooks.py --remove   # 卸载 hooks
```

**安装后需重启 CodeBuddy（或在 `/hooks` 面板审核应用）才生效。**

### 手动配置（可选）

等价于把下面这段合并进 `~/.codebuddy/settings.json`（替换 `<skill>` 为实际路径）：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python \"<skill>/scripts/agent_log_hook.py\"", "timeout": 30 } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "python \"<skill>/scripts/agent_log_hook.py\"", "timeout": 30 } ] }
    ]
  }
}
```

> hook 任何异常都以 exit 0 结束，绝不会阻塞 CodeBuddy 会话。

## 配置项

| 配置 | 默认 | 说明 |
|------|------|------|
| `qaLog.pythonPath` | `python` | Python 可执行文件 |
| `qaLog.dbPath` | 空 | `qa.db` 路径；留空 = 当前工作区根目录下的 `qa.db` |
| `qaLog.scriptPath` | 空 | `qa_query.py` 路径；留空则按常见 skill 安装位置自动查找 |

## 数据流

```
CodeBuddy 会话
  └─ hooks(UserPromptSubmit / Stop)
       └─ scripts/agent_log_hook.py  ──写入──▶  <项目根>/qa.db  ── agent_log
                                                 qa_entries（QA 记录）
本扩展（只读）
  └─ scripts/qa_query.py  ──JSON──▶  侧边栏列表 + 中间区域详情面板
```

## 已知限制

- **Agent 回复正文无法展示**：CodeBuddy 把会话正文存在受保护的 `messages`
  文件里（实测 Win32 `ACCESS_DENIED`）。因此 Agent 日志视图只展示
  **用户输入历史**（回复的完成摘要在数据库中留档，未来若开放正文可补展示）。
- 无法通过扩展直接跳转到 CodeBuddy 的某个会话（CodeBuddy 未提供按会话 ID
  打开的公开命令/URI，仅有 chatHistory 打开历史列表，且经评估未集成）。
- 日志按项目严格隔离：每个项目一份 `qa.db`（与 QA 记录同库），插件只读当前
  工作区对应的 `qa.db`，无全局汇总库；hook 写入为短连接（commit 后立即
  close），不长期占用文件锁。
