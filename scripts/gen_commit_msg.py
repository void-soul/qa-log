#!/usr/bin/env python3
"""生成描述性commit message，确保UTF-8编码无乱码"""
import sys
import json
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
    """生成commit message"""
    qid = data.get('id', 'Q-000')
    description = data.get('description', '')
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
    parser.add_argument('--id', '-q', help='QA ID (e.g., Q-001)')
    parser.add_argument('--desc', '-d', help='Description')
    
    args = parser.parse_args()
    
    # 从stdin读取JSON
    if sys.stdin.isatty():
        # 非管道模式，从命令行参数读取
        data = {
            'id': args.id,
            'description': args.desc,
            'type': args.type
        }
    else:
        # 管道模式，从stdin读取
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input", file=sys.stderr)
            sys.exit(1)
    
    # 补充参数
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
