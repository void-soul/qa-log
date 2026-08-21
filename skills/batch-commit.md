---
name: qa-log-batch-commit
description: "根据qa.db条目内容分批次提交代码。当用户要求'按QA提交'或'分批commit'时触发，支持按文件组/功能点分组，避免一次性提交全部代码。"
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, git, commit, batch, submission]
    related_skills: [qa-log, qa-log-check, secure-git-commit]
---

# QA Log Batch Commit — 分批次提交代码

当用户要求按QA条目分批次提交代码时使用此技能。核心原则：**按改动内容分组，而非一次性全部提交**。

## 触发条件

- 用户说："按Q-XXX提交"、"分批commit这些修改"、"先提交Q-001再提交Q-002"
- 需要为QA条目生成带描述性commit message的提交

## 工作流程

### 1. 确定提交范围

```bash
cd <project-root> && python scripts/qa_tool.py get <ID>
```

提取「涉及文件」表格中的所有文件。

### 2. 分组策略（按内容而非数量）

根据改动类型分组：

| 分组依据 | 示例 |
|---------|------|
| 同一功能模块 | 前端组件 + 对应API接口 |
| 同一问题修复 | 修复Q-XXX涉及的所有文件 |
| 不同业务领域 | 订单模块 / 用户模块 / 支付模块 |
| 配置变更 | 单独一组，不与其他代码混合 |

### 3. 生成commit message（CRITICAL：无乱码 + 英文）

Commit message 的 `description` 一律使用**英文**。使用Python脚本确保UTF-8编码：

```python
# scripts/gen_commit_msg.py
import sys
import json

data = json.load(sys.stdin)
qid = data['id']
files = data['files']
change_type = data.get('type', 'fix')  # fix, feat, refactor, test

# 根据文件内容推断简洁描述（英文）
desc = data.get('description', f"Fix issue #{qid}")

msg = f"{change_type}: #{qid} {desc}"
print(msg.encode('utf-8').decode('utf-8'))  # 显式UTF-8
```

调用方式（description 用英文）：
```bash
echo '{"id":"Q-001","files":["app.py","config.yaml"],"description":"Fix save button not responding"}' | python scripts/gen_commit_msg.py
```

### 4. 分批执行提交

**第一批**：
```bash
cd <project-root>
git add <file1> <file2>
git commit -m "$(echo '{"id":"Q-001","files":["app.py"],"description":"Fix save button not responding"}' | python scripts/gen_commit_msg.py)"
```

**第二批**（如有）：
```bash
git add <file3> <file4>
git commit -m "$(echo '{"id":"Q-002","files":["component.vue"],"description":"Add export feature"}' | python scripts/gen_commit_msg.py)"
```

### 5. 每批提交后确认

每批提交完成后，输出：
```
✅ 第 N 批已提交: Q-XXX
   文件: file1, file2
   Commit: <hash>
```

等待用户确认后再继续下一批。

## 乱码预防措施

1. **始终使用Python处理中文参数**，不在shell中直接传递中文
2. **commit message通过stdin传递**，避免命令行编码问题
3. **统一使用UTF-8编码**，脚本开头设置 `sys.stdout.reconfigure(encoding="utf-8")`
4. **Windows环境下**，使用 `chcp 65001` 切换代码页

## 与 secure-git-commit 的协作

- 如果用户未明确要求分批次，先运行 `secure-git-commit` 进行审查
- 审查通过后，再使用本技能进行分批次提交
- 两者组合：`secure-git-commit` → `qa-log-batch-commit`

## 示例

用户："请帮我按Q-001和Q-002分批提交代码"

1. 查询Q-001和Q-002的涉及文件
2. 按功能分组：
   - 批1: Q-001的文件（保存按钮修复）
   - 批2: Q-002的文件（导出功能）
3. 逐批执行git add + git commit
4. 每批完成后询问用户是否继续
