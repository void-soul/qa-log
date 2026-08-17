---
name: qa-log
description: "Use when the user asks a programming question or requests a code change. Logs the question and its solution to QA.md in the project root using a structured 4-section format: 现象/需求, 根因, 解决方案, 涉及文件. Supports multi-question decomposition and token-efficient retrieval via scripts."
version: 2.5.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, logging, documentation, context, programming]
    related_skills: [code-audit, systematic-debugging]
---

# QA Log — Cross-Session Context Preservation

当用户提出编程问题或要求代码变更时，使用此技能记录问题和解决方案到 `QA.md`。

**核心原则：** 每个解决的问题都成为可搜索的参考。

## 对外提供的能力

### 能力1: 记录问题与解决方案

**触发条件：** 用户提出编程问题、调试请求或代码变更要求

**工作流程：**
1. 加载 `qa-log/skills/add-question` 技能，记录问题
2. 正常解决问题
3. 加载 `qa-log/skills/fill-solution` 技能，记录解决方案

### 能力2: 检查QA条目

**触发条件：** 用户说 "请检查Q-XXX" 或类似请求

**工作流程：**
1. 加载 `qa-log/skills/check` 技能
2. 提取条目、分析、审查代码、做出判断、更新状态
3. **询问用户是否提交**（检查通过后必须）
4. 仅在用户确认后提交涉及的代码文件

### 辅助能力

**搜索条目：** 加载 `qa-log/skills/search` 技能，按关键词、状态、类别搜索历史QA记录

**格式检查：** 加载 `qa-log/skills/format-doc` 技能，验证和修复 QA.md 结构

**分批次提交：** 加载 `qa-log/skills/batch-commit` 技能，按功能分组提交代码，避免一次性提交全部

## 何时跳过

- 非编程问题
- 简单事实查询
- 用户明确说"跳过QA记录"

## 子技能

|| 技能 | 用途 |
||------|------|
|| `qa-log/skills/add-question` | Phase 1: 记录问题 |
|| `qa-log/skills/fill-solution` | Phase 3: 填写方案 |
|| `qa-log/skills/check` | 检查验证 |
|| `qa-log/skills/format-doc` | 格式检查 |
|| `qa-log/skills/search` | 搜索历史QA条目 |
|| `qa-log/skills/batch-commit` | 分批次提交代码 |

## CLI 参考（scripts/qa_tool.py）

`qa_tool.py` 直接读写 `QA.md`，支持以下子命令：

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `summary` | — | 列出所有条目（ID + 标题） |
| `get <ID>` | `ID`（如 `Q-003` 或 `3`） | 查看单条完整内容 |
| `append` | `-c/--category`, `-q/--question` | 新增条目（ID 自动递增，状态默认 Pending） |
| `update <ID>` | `-q/--question`, `-s/--status`, `-r/--root-cause`, `-a/--answer`, `-f/--files` | 更新已有条目 |
| `next-id` | — | 打印下一个可用 ID |
| `format` | — | 校验并报告 QA.md 结构问题 |

**`update` 可修改字段说明：**
- `-q/--question`：覆盖「现象/需求」字段（即新增时写入的问题文本）。**用于修正乱码或改写需求描述**。
- `-s/--status`：状态（`Pending` / `已解决待验证` / `已验证` / `WontFix` / `Unresolved`）。
- `-r/--root-cause`：根因分析（覆盖「根因」）。
- `-a/--answer`：解决方案步骤（覆盖「解决方案」）。
- `-f/--files`：变更文件表（覆盖「涉及文件」，`| File | Change |` 格式）。

所有文本参数中字面量 `\\n` 会被展开为真实换行；多行内容建议用 `\\n` 拼接。

> **乱码预防：** 所有脚本已强制使用UTF-8编码（`sys.stdout.reconfigure(encoding="utf-8")`）。Windows环境下如需在命令行直接使用，请先执行 `chcp 65001` 切换到UTF-8代码页。推荐通过Python调用避免编码问题。

## 技能组织说明

所有子技能统一存放在 `qa-log/skills/` 目录下，通过嵌套路径访问。不要创建单独的顶级子技能目录。

详见 [`references/skill-organization-pattern.md`](references/skill-organization-pattern.md)