---
name: qa-log-search
description: "搜索 qa.db 中的 QA 条目。当用户需要查找历史问题时使用，支持按ID、关键词、状态、类别筛选。"
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, search, lookup, history]
    related_skills: [qa-log, qa-log-check]
---

# QA Log Search — 搜索历史QA条目

当用户需要查找、回顾或引用历史QA记录时使用此技能。

> **v2.0**：数据源由 `QA.md` 改为 `qa.db`（SQLite），位于**项目根目录**。运行脚本前先 `cd <project-root>`。

## 触发条件

- 用户说："搜索Q-XXXX"、"查找之前关于XXX的问题"
- 需要回顾某个类别的所有问题
- 用户问："有哪些Pending状态的问题？"

## 使用方法

### 基础搜索

```bash
# 按ID查看完整条目
cd <project-root> && python scripts/qa_tool.py get Q-XXXX

# 列出所有条目摘要
cd <project-root> && python scripts/qa_tool.py summary

# 查看下一个可用ID
cd <project-root> && python scripts/qa_tool.py next-id
```

### 高级搜索（search_qa.py）

使用 `scripts/search_qa.py` 按关键词、状态、类别筛选：

```bash
# 按关键词搜索
cd <project-root> && python scripts/search_qa.py 保存

# 按状态筛选
cd <project-root> && python scripts/search_qa.py --status Pending

# 按类别搜索
cd <project-root> && python scripts/search_qa.py --category Bug

# 组合筛选
cd <project-root> && python scripts/search_qa.py --status Pending --category Bug

# 限制结果数量
cd <project-root> && python scripts/search_qa.py 保存 -n 20
```

## 输出格式

```
Found 3 entries:

## Q-0029 | 2026-08-02 | Bug Fix | 已验证
修改了 **app.py** 中的 **Width** 属性...
---

## Q-0030 | 2026-08-03 | Feature | 已解决待验证
新增导出功能...
---
```

## 注意事项

1. **乱码预防**：所有输出强制使用UTF-8编码
2. **大小写不敏感**：搜索时忽略大小写
3. **模糊匹配**：支持部分关键词匹配
4. **结果限制**：默认返回10条，可通过 `-n` 参数调整
5. **若 qa.db 不存在**：先运行 `python scripts/qa_tool.py setup`
