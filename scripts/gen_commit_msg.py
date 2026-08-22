#!/usr/bin/env python3
"""生成描述性commit message（英文），确保UTF-8编码无乱码"""
import sys
import json
import os
import argparse

# 强制UTF-8输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

# commit类型映射
TYPE_MAP = {
    'fix': 'fix',
    'feat': 'feat', 
    'refactor': 'refactor',
    'test': 'test',
    'docs': 'docs',
    'chore': 'chore',
    'style': 'style',
    'perf': 'perf'
}

def generate_message(data):
    """生成commit message（description 应为英文）"""
    qid = data.get('id', 'Q-0000')
    description = data.get('description', '') or f"Fix issue #{qid}"
    change_type = data.get('type', 'fix')
    
    # 规范化type
    commit_type = TYPE_MAP.get(change_type.lower(), 'fix')
    
    # 构建message
    msg = f"{commit_type}: #{qid} {description}"
    
    return msg

def main():
    parser = argparse.ArgumentParser(description="Generate commit message from JSON data")
    parser.add_argument('--input', '-i', help='Input JSON file or string')
    parser.add_argument('--type', '-t', default='fix', help='Commit type (fix/feat/refactor/test)')
    parser.add_argument('--id', '-q', help='QA ID (e.g., Q-0001)')
    parser.add_argument('--desc', '-d', help='Description')
    
    args = parser.parse_args()
    
    # 数据来源优先级：--input > 命令行参数(--id/--desc/--type) > stdin(管道)
    data = {}
    if args.input:
        # --input 指定了 JSON 字符串或文件路径
        try:
            if os.path.exists(args.input):
                with open(args.input, "r", encoding="utf-8") as f:
                    raw = f.read()
            else:
                raw = args.input
            data = json.loads(raw)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input", file=sys.stderr)
            sys.exit(1)
    elif not sys.stdin.isatty():
        # 管道模式，从stdin读取
        raw = sys.stdin.read()
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print("Error: Invalid JSON input", file=sys.stderr)
                sys.exit(1)

    # 命令行参数覆盖/补充
    if args.id:
        data['id'] = args.id
    if args.desc:
        data['description'] = args.desc
    if args.type:
        data['type'] = args.type

    msg = generate_message(data)
    print(msg)

if __name__ == "__main__":
    main()
