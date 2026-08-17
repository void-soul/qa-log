---
name: qa-log-search
description: "搜索QA条目。当用户需要查找历史问题时使用，支持按ID、关键词、状态、类别筛选。"
version: 1.0.0
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

## 触发条件

- 用户说："搜索Q-XXX"、"查找之前关于XXX的问题"
- 需要回顾某个类别的所有问题
- 用户问："有哪些Pending状态的问题？"

## 使用方法

### 基础搜索

```bash
# 按ID查看完整条目
cd <project-root> && python scripts/qa_tool.py get Q-XXX

# 列出所有条目摘要
cd <project-root> && python scripts/qa_tool.py summary

# 查看下一个可用ID
cd <project-root> && python scripts/qa_tool.py next-id
```

### 高级搜索（Python脚本）

创建搜索脚本 `scripts/search_qa.py`：

```python
#!/usr/bin/env python3
"""搜索QA.md条目"""
import argparse
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QA_MD = "QA.md"

def read_qa_md():
    if not os.path.exists(QA_MD):
        return ""
    with open(QA_MD, "r", encoding="utf-8") as f:
        return f.read()

def search_entries(content, query=None, status=None, category=None, limit=10):
    """搜索条目"""
    entries = []
    pattern = re.compile(r'^## (Q-\d+) \| (\d{4}-\d{2}-\d{2}) \| (.+?) \| (\w+)\n\n(.*?)(?=\n---\n|\Z)', re.DOTALL | re.MULTILINE)
    
    for match in pattern.finditer(content):
        qid, date, cat, stat, body = match.groups()
        
        # 过滤条件
        if status and stat != status:
            continue
        if category and category.lower() not in cat.lower():
            continue
        if query:
            # 在标题和内容中搜索
            title_match = query.lower() in qid.lower() or query.lower() in body.lower()
            if not title_match:
                continue
        
        entries.append({
            'id': qid,
            'date': date,
            'category': cat.strip(),
            'status': stat.strip(),
            'body': body.strip()[:200] + '...' if len(body) > 200 else body.strip()
        })
        
        if len(entries) >= limit:
            break
    
    return entries

def main():
    parser = argparse.ArgumentParser(description="Search QA entries")
    parser.add_argument("query", nargs="?", help="Search query (keyword or Q-ID)")
    parser.add_argument("-s", "--status", help="Filter by status")
    parser.add_argument("-c", "--category", help="Filter by category")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max results")
    
    args = parser.parse_args()
    
    content = read_qa_md()
    if not content:
        print("QA.md not found.")
        return
    
    results = search_entries(content, args.query, args.status, args.category, args.limit)
    
    if not results:
        print("No matching entries found.")
        return
    
    print(f"Found {len(results)} entries:\n")
    for r in results:
        print(f"## {r['id']} | {r['date']} | {r['category']} | {r['status']}")
        print(f"{r['body'][:100]}...")
        print("---")

if __name__ == "__main__":
    import os
    main()
```

### 搜索命令

```bash
# 按关键词搜索
cd <project-root> && python scripts/search_qa.py 保存

# 按状态筛选
cd <project-root> && python scripts/search_qa.py --status Pending

# 按类别搜索
cd <project-root> && python scripts/search_qa.py --category Bug

# 组合筛选
cd <project-root> && python scripts/search_qa.py --status Pending --category Bug
```

## 输出格式

```
Found 3 entries:

## Q-029 | 2024-01-15 | Bug Fix | 已验证
修改了 **app.py** 中的 **Width** 属性...
---

## Q-030 | 2024-01-16 | Feature | 已解决待验证
新增导出功能...
---
```

## 注意事项

1. **乱码预防**：所有输出强制使用UTF-8编码
2. **大小写不敏感**：搜索时忽略大小写
3. **模糊匹配**：支持部分关键词匹配
4. **结果限制**：默认返回10条，可通过 `-n` 参数调整
