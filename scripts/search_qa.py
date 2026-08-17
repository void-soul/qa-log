#!/usr/bin/env python3
"""搜索QA.md条目"""
import argparse
import os
import re
import sys

# 强制UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

QA_MD = "QA.md"

def read_qa_md():
    """读取QA.md"""
    if not os.path.exists(QA_MD):
        return ""
    with open(QA_MD, "r", encoding="utf-8") as f:
        return f.read()

def search_entries(content, query=None, status=None, category=None, limit=10):
    """搜索条目"""
    entries = []
    
    # 匹配条目头部
    header_pattern = re.compile(r'^## (Q-\d+) \| (\d{4}-\d{2}-\d{2}) \| (.+?) \| (\w+)', re.MULTILINE)
    separator_pattern = re.compile(r'^---$', re.MULTILINE)
    
    headers = list(header_pattern.finditer(content))
    separators = list(separator_pattern.finditer(content))
    
    for i, header in enumerate(headers):
        qid = header.group(1)
        date = header.group(2)
        cat = header.group(3).strip()
        stat = header.group(4).strip()
        
        # 获取条目内容范围
        start = header.start()
        end = separators[i].start() if i < len(separators) else len(content)
        body = content[start:end]
        
        # 过滤条件
        if status and stat != status:
            continue
        if category and category.lower() not in cat.lower():
            continue
        if query:
            query_lower = query.lower()
            # 在QID、类别、状态中搜索
            id_match = query_lower in qid.lower()
            cat_match = query_lower in cat.lower()
            stat_match = query_lower in stat.lower()
            # 在正文中搜索（去除markdown格式）
            body_clean = re.sub(r'\*\*', '', body)  # 去除粗体标记
            body_match = query_lower in body_clean.lower()
            
            if not (id_match or cat_match or stat_match or body_match):
                continue
        
        # 提取现象/需求作为摘要
        phenomenon_match = re.search(r'\*\*现象/需求:\*\*\s*(.+?)(?:\n|$)', body, re.DOTALL)
        summary = phenomenon_match.group(1).strip()[:80] + '...' if phenomenon_match else '...'
        
        entries.append({
            'id': qid,
            'date': date,
            'category': cat,
            'status': stat,
            'summary': summary,
            'raw': body
        })
        
        if len(entries) >= limit:
            break
    
    return entries

def main():
    parser = argparse.ArgumentParser(description="Search QA entries")
    parser.add_argument("query", nargs="?", help="Search query (keyword or Q-ID)")
    parser.add_argument("-s", "--status", help="Filter by status (Pending, 已解决待验证, 已验证, WontFix, Unresolved)")
    parser.add_argument("-c", "--category", help="Filter by category (Bug Fix, Feature, etc.)")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max results (default: 10)")
    
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
        print(f"{r['summary']}")
        print("---")

if __name__ == "__main__":
    main()
