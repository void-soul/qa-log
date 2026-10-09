# QA Log — VSCode / CodeBuddy 扩展

<img src="media/otter-color.png" alt="QA Log otter IP" width="96" align="right" />

在侧边栏浏览项目根目录的 `qa.db`，包含三个视图：

| 入口 | 视图 | 数据 |
|------|------|------|
| 🗒️ **QA 记录** | 搜索 / 状态筛选，点击在 IDE 中间区域查看详情；字段按 **Markdown 渲染**，支持**编辑 / 删除**，涉及文件里的路径**可点击直接打开**（相对路径按工作区根解析，支持 `file.ts:123` 行号） | `qa_entries` 表 |
| 💬 **Agent 日志** | 用户输入历史（时间倒序，单行省略），悬停行尾 `⧉` 一键复制，点击在中间区域打开**会话原文浏览**（可搜索定位） | `agent_log` 表 |
| 🩺 **记忆健康**（P4） | 7 张统计卡（总条目 / 已归档 / 待审冲突 / 待验证积压 / 孤立条目 / 7 天新增 / 7 天召回）+ 状态分布 + 四个建议区块（近似重复对 / 冲突待审 / 待验证积压 / 孤立条目），可按 QID 筛选 | 由 `qa_query.py health` 实时计算（`qa_entries` + `qa_links` + `qa_events`） |

前两个视图均为：侧边栏单列列表（虚拟滚动）+ 点击在 IDE 中间区域打开详情面板（复用，非弹窗）；记忆健康视图为单页报告。样式跟随 VSCode 主题；活动栏图标为单色 otter 字形（跟随主题变色），强化标识图如上。

**会话原文浏览面板**：上半为消息列表（虚拟滚动、懒加载），下半为选中消息全文，中间分隔条可拖动调整比例；工具栏搜索框支持全文搜索（回车触发），命中后在列表中标记、`↑`/`↓` 循环跳转并高亮，下方自动展示该条全文。

## 前置条件

### 1. Python（**必需**，扩展不做任何 SQLite 直连）

扩展的**全部读写**（列表、详情、编辑、删除、健康报告、召回）都是启动 `scripts/qa_query.py`
子进程完成的——Node 侧**零 SQLite 依赖**，因此必须能调用 Python。

| 项目 | 要求 |
|------|------|
| 版本 | **≥ 3.7**（用到 `sys.stdout.reconfigure(encoding=...)`，3.7 才有）；**建议 ≥ 3.9**，实测环境 **3.11.9** |
| 第三方包 | **无**。只用标准库：`sqlite3` / `json` / `argparse` / `re` / `math` / `datetime` |
| 定位方式 | 默认用 PATH 里的 `python`；也接受 `py -3`（Windows 官方安装器）、完整路径（如 `D:\any-versions\sdk\python\python.exe`） |
| 指定方式 | 设置项 `qaLog.pythonPath`（见「配置项」） |
| 找不到时 | 扩展自动回退 `py -3`；仍失败则在视图里报「找不到 Python」，并在 `QA Log` 输出通道留诊断 |

> 若 `python` 不在 PATH 且只有 `py -3`，**务必设置 `qaLog.pythonPath`**：CodeBuddy 的 hooks
> 是写进 `~/.codebuddy/settings.json` 的命令行，扩展会用同一配置生成它（写死 `python` 会让 hook 静默失效）。

自检（应打印版本号且无报错）：

```bash
python --version
python <skill>/scripts/qa_query.py --db <项目根>/qa.db stats
```

### 2. 数据库

项目根目录已有 `qa.db`（在该项目首次使用 qa-log skill 时由
`python <skill>/scripts/qa_tool.py setup` 创建）。缺失的表/列会在每次访问时自动幂等补齐。

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
>
> 若 `python` 不在 PATH，把命令里的 `python` 换成实际可用的形式（`py -3`，或带引号的完整路径）；
> 用扩展的「启用 hooks」按钮会自动按 `qaLog.pythonPath` 生成正确的命令。

## 配置项

| 配置 | 默认 | 说明 |
|------|------|------|
| `qaLog.pythonPath` | `python` | Python 可执行文件 / 命令。可填 `python`、`py -3` 或**完整路径**（路径含空格也会被正确引用）；**扩展与 hooks 共用此配置**，找不到 `python` 时自动回退 `py -3` |
| `qaLog.dbPath` | 空 | `qa.db` 路径；留空 = 当前工作区根目录下（或向上 12 层内第一个含 `qa.db` 的目录）的 `qa.db` |
| `qaLog.scriptPath` | 空 | `qa_query.py` 路径；留空则按 `~/.claude` / `~/.agents` / `~/.codebuddy` 的 skills 目录与工作区 `scripts/` 自动查找（**不会**使用任何硬编码的绝对路径） |

## 数据流

```
CodeBuddy 会话
  └─ hooks(UserPromptSubmit / Stop)      ← 命令里的 Python 取自 qaLog.pythonPath
       └─ scripts/agent_log_hook.py  ──写入──▶  <项目根>/qa.db  ── agent_log
                                                 qa_entries（QA 记录）
                                                 qa_links / qa_events（关系 / 审计）

本扩展（读写都走 Python 子进程，JSON 单行输出）
  └─ scripts/qa_query.py <action>  ──JSON──▶  侧边栏三个视图
        qa-list / log-list / log-sessions / projects / stats   → 列表
        qa-get                                                 → 中间区域详情面板
        qa-update / qa-delete（JSON 走 stdin）                  → 编辑 / 删除
        health                                                 → 记忆健康视图
        recall                                                 → 加权召回
```

> 中文内容一律经 **stdin JSON** 传递（`qa_query.py` 已强制 UTF-8），不走命令行参数，
> 避免 Windows GBK 代码页破坏中文。

## 已知限制

- **会话原文浏览**：点击日志记录会在编辑器中间区域打开会话浏览面板
  （上列表 + 下全文）。数据来自 CodeBuddy 本地会话存储
  （`%LOCALAPPDATA%\CodeBuddyExtension\Data\...\history\<wsHash>\<sessionId>\`，
  `index.json` 有序骨架 + `messages/<id>.json` 正文，均可读）；tool / 思考过程
  默认一行摘要，点击行在下方看全文；列表按需懒加载，长会话不卡。
  旧版记录（未记录 transcript 路径）按 sessionId 扫描定位，找不到则回落到
  简单详情面板。
- **记忆健康视图的开销**：每次刷新会跑一次全表相似度扫描（O(n²)，带无假阴性上界剪枝）。
  实测 549 条库 ≈ 1.1s、1200 条量级预计数秒；刷新是异步子进程，不阻塞 UI，但超大库会感到延迟。
- 无法通过扩展直接跳转到 CodeBuddy 的某个会话（CodeBuddy 未提供按会话 ID
  打开的公开命令/URI，仅有 chatHistory 打开历史列表，且经评估未集成）。
- 日志按项目严格隔离：每个项目一份 `qa.db`（与 QA 记录同库），插件只读当前
  工作区对应的 `qa.db`，无全局汇总库；hook 写入为短连接（commit 后立即
  close），不长期占用文件锁。
