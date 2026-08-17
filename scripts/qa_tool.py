#!/usr/bin/env python3
"""
QA.md management toolkit — read/write QA entries without loading the entire file.

QA.md format:
# QA Log

## Q-NNN | YYYY-MM-DD | Category | Status

**现象/需求:** [Phenomenon or requirement]

**根因:** [Root cause analysis]

**解决方案:** [Solution steps]

**涉及文件:**
| File | Change |
|------|--------|
| path/to/file | What was changed |

---

Subcommands:
  summary              List all questions (ID + title only)
  get <ID>             Get full content of a single question by ID
  append               Append a new question (auto-increments ID)
  update <ID>          Update an existing question's solution/status
  next-id              Print the next available ID
  format               Validate and reformat QA.md
"""

import argparse
import os
import re
import sys
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QA_MD = "QA.md"
PLACEHOLDER = "[待填写]"

ENTRY_HEADER_RE = re.compile(
    r'^## (Q-\d+) \| (\d{4}-\d{2}-\d{2}) \| (.+?) \| (\w+)',
    re.MULTILINE
)

# Valid status values
VALID_STATUSES = {"Pending", "已解决待验证", "已验证", "WontFix", "Unresolved"}


def read_qa_md():
    """Read QA.md content, return empty string if not exists."""
    if not os.path.exists(QA_MD):
        return ""
    with open(QA_MD, "r", encoding="utf-8") as f:
        return f.read()


def write_qa_md(content):
    """Write content to QA.md."""
    with open(QA_MD, "w", encoding="utf-8") as f:
        f.write(content)


def ensure_qa_md():
    """Create QA.md with header if it doesn't exist."""
    if not os.path.exists(QA_MD):
        write_qa_md("# QA Log\n\n编程问答记录。\n\n---\n\n")
    return read_qa_md()


def find_entries(content):
    """Parse all entries from QA.md content.
    Returns list of dicts with: id, date, category, status, start, end
    """
    entries = []
    for m in ENTRY_HEADER_RE.finditer(content):
        entries.append({
            "id": m.group(1),
            "date": m.group(2),
            "category": m.group(3).strip(),
            "status": m.group(4).strip(),
            "start": m.start(),
        })
    for i, entry in enumerate(entries):
        entry["end"] = entries[i + 1]["start"] if i + 1 < len(entries) else len(content)
    return entries


def get_next_id(content):
    """Find the highest existing ID and return next one."""
    entries = find_entries(content)
    if not entries:
        return "Q-001"
    max_num = max(int(re.search(r'Q-(\d+)', e["id"]).group(1)) for e in entries)
    return f"Q-{max_num + 1:03d}"


def extract_field(section, field_name, default=""):
    """Extract a field value from an entry section. Handles multi-line values and tables."""
    lines = section.split("\n")
    for i, line in enumerate(lines):
        # Match field header like **现象/需求:** or **根因:** etc.
        if line.startswith(f"**{field_name}:**") or line.startswith(f"**{field_name}**"):
            # Find the colon after the field name (skip the ** prefix)
            # Pattern: **FieldName:** value
            pattern = f"**{field_name}:**"
            colon_start = line.find(pattern)
            if colon_start == -1:
                continue
            # Position after the pattern (which ends with :)
            val_start = colon_start + len(pattern)
            val = line[val_start:].strip()
            # If value is empty, check subsequent lines for table or multi-line content
            if not val and i + 1 < len(lines):
                sub_lines = []
                j = i + 1
                while j < len(lines) and lines[j].strip() and not lines[j].startswith("**"):
                    sub_lines.append(lines[j])
                    j += 1
                return "\n".join(sub_lines) if sub_lines else default
            if val and val != PLACEHOLDER:
                return val
    return default


def get_raw_field(section, field_name):
    """Extract raw field value (including placeholder) from an entry section.
    Handles multi-line values and tables.
    """
    lines = section.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(f"**{field_name}:**") or line.startswith(f"**{field_name}**"):
            # Find the colon after the field name (skip the ** prefix)
            pattern = f"**{field_name}:**"
            colon_start = line.find(pattern)
            if colon_start == -1:
                continue
            val_start = colon_start + len(pattern)
            first_line = line[val_start:].strip()

            # If first line has content, collect subsequent lines until blank or **
            if first_line:
                parts = [first_line]
                j = i + 1
                while j < len(lines) and lines[j].strip() and not lines[j].startswith("**"):
                    parts.append(lines[j])
                    j += 1
                return "\n".join(parts)

            # First line is empty, check subsequent lines for table or multi-line content
            sub_lines = []
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].startswith("**"):
                sub_lines.append(lines[j])
                j += 1
            return "\n".join(sub_lines) if sub_lines else ""
    return ""


def make_entry(entry_id, date_str, category, status, phenomenon, root_cause, solution, files_table):
    """Build a single entry string in four-section format."""
    # Default placeholder for unsolved entries
    if not root_cause:
        root_cause = PLACEHOLDER
    if not solution:
        solution = PLACEHOLDER
    if not files_table:
        files_table = PLACEHOLDER

    # Build files section - either table or placeholder
    if "\n" in files_table or files_table == PLACEHOLDER:
        files_section = f"**涉及文件:**\n{files_table}" if files_table != PLACEHOLDER else f"**涉及文件:** {files_table}"
    else:
        files_section = f"**涉及文件:**\n{files_table}"

    return (
        f"## {entry_id} | {date_str} | {category} | {status}\n\n"
        f"**现象/需求:** {phenomenon}\n\n"
        f"**根因:** {root_cause}\n\n"
        f"**解决方案:** {solution}\n\n"
        f"{files_section}\n\n"
        f"---\n"
    )


def normalize_id(id_str):
    """Normalize ID to Q-NNN format."""
    id_str = id_str.strip().upper()
    if not id_str.startswith("Q-"):
        num = id_str.lstrip("Q-").lstrip("0") or "1"
        id_str = f"Q-{int(num):03d}"
    return id_str


def cmd_summary(args):
    """List all questions: ID + title only."""
    content = read_qa_md()
    if not content:
        print("QA.md not found.")
        return
    entries = find_entries(content)
    if not entries:
        print("No entries found.")
        return
    for entry in entries:
        section = content[entry["start"]:entry["end"]]
        title = extract_field(section, "现象/需求")
        # Truncate long titles
        if len(title) > 50:
            title = title[:47] + "..."
        print(f"{entry['id']} | {entry['date']} | {entry['category']} | {entry['status']} | {title}")


def cmd_get(args):
    """Get full content of a single entry by ID."""
    content = read_qa_md()
    if not content:
        print("QA.md not found.")
        sys.exit(1)
    entries = find_entries(content)
    target = normalize_id(args.id)
    for entry in entries:
        if entry["id"] == target:
            print(content[entry["start"]:entry["end"]].rstrip())
            return
    print(f"Entry {target} not found.")
    sys.exit(1)


def cmd_append(args):
    """Append a new question entry with auto-generated ID."""
    content = ensure_qa_md()
    entry_id = get_next_id(content)
    today = date.today().isoformat()
    category = args.category or "Other"
    question = args.question or ""

    entry = make_entry(
        entry_id, today, category, "Pending",
        question, PLACEHOLDER, PLACEHOLDER, PLACEHOLDER
    )

    content = content.rstrip("\n") + "\n" + entry
    write_qa_md(content)
    print(f"Created {entry_id}")


def cmd_update(args):
    """Update an existing entry's solution and status."""
    content = read_qa_md()
    if not content:
        print("QA.md not found.")
        sys.exit(1)
    entries = find_entries(content)
    target = normalize_id(args.id)

    for entry in entries:
        if entry["id"] == target:
            section = content[entry["start"]:entry["end"]]

            # Extract existing fields
            existing_phenomenon = extract_field(section, "现象/需求")
            existing_root_cause = get_raw_field(section, "根因")
            existing_solution = get_raw_field(section, "解决方案")
            existing_files = get_raw_field(section, "涉及文件") or PLACEHOLDER

            # Clean up any stray leading ** from phenomenon (caused by markdown bold parsing)
            if existing_phenomenon.startswith("** "):
                existing_phenomenon = existing_phenomenon[3:]
            elif existing_phenomenon.startswith("**"):
                existing_phenomenon = existing_phenomenon[2:]

            # Also clean root_cause and solution if they have stray leading **
            if existing_root_cause.startswith("** "):
                existing_root_cause = existing_root_cause[3:]
            elif existing_root_cause.startswith("**"):
                existing_root_cause = existing_root_cause[2:]

            if existing_solution.startswith("** "):
                existing_solution = existing_solution[3:]
            elif existing_solution.startswith("**"):
                existing_solution = existing_solution[2:]

            # Override with new values if provided
            status = args.status or entry["status"]
            phenomenon = args.question if args.question is not None else existing_phenomenon
            root_cause = args.root_cause if args.root_cause is not None else existing_root_cause
            solution = args.answer if args.answer is not None else existing_solution
            files_table = args.files if args.files is not None else existing_files

            # Expand literal \n to actual newlines
            if root_cause:
                root_cause = root_cause.replace("\\n", "\n")
            if solution:
                solution = solution.replace("\\n", "\n")
            if files_table:
                files_table = files_table.replace("\\n", "\n")

            new_section = make_entry(
                entry["id"], entry["date"], entry["category"], status,
                phenomenon, root_cause, solution, files_table
            )

            content = content[:entry["start"]] + new_section + content[entry["end"]:]
            write_qa_md(content)
            print(f"Updated {target}")
            return

    print(f"Entry {target} not found.")
    sys.exit(1)


def cmd_next_id(args):
    """Print the next available ID without creating anything."""
    content = read_qa_md()
    if not content:
        print("Q-001")
        return
    print(get_next_id(content))


def cmd_format(args):
    """Validate and reformat QA.md for consistent structure."""
    content = read_qa_md()
    if not content:
        print("QA.md not found.")
        return

    entries = find_entries(content)
    if not entries:
        print("No entries found.")
        return

    issues = []
    fixed = 0

    for entry in entries:
        section = content[entry["start"]:entry["end"]]
        lines = section.split("\n")

        # Check 1: Header format
        header = lines[0] if lines else ""
        if not re.match(r'^## Q-\d+ \| \d{4}-\d{2}-\d{2} \| .+? \| \w+', header):
            issues.append(f"{entry['id']}: Header format issue")

        # Check 2: Status validation
        current_status = entry["status"]
        if current_status not in VALID_STATUSES:
            issues.append(f"{entry['id']}: Invalid status '{current_status}'")

        # Check 3: Field format - verify fields exist (don't flag empty lines as issues)
        for i, line in enumerate(lines):
            if line.startswith("**解决方案:**") or line.startswith("**涉及文件:**"):
                # Check that there's at least some content after (table or text)
                has_content = False
                for j in range(i + 1, len(lines)):
                    stripped = lines[j].strip()
                    if stripped.startswith("|"):
                        has_content = True
                        break
                    elif stripped == "**":
                        # Skip stray ** lines
                        continue
                    elif stripped and not stripped.startswith("**"):
                        has_content = True
                        break
                    elif stripped.startswith("**"):
                        break
                if not has_content:
                    issues.append(f"{entry['id']}: {line.strip()} missing content")

    if issues:
        print(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"Formatted {len(entries)} entries — all valid")


def main():
    parser = argparse.ArgumentParser(
        description="QA.md management toolkit — read/write without loading entire file"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summary", help="List all questions (ID + title)")

    p_get = sub.add_parser("get", help="Get full content of one question")
    p_get.add_argument("id", help="Question ID (e.g., Q-003 or just 3)")

    p_append = sub.add_parser("append", help="Append a new question")
    p_append.add_argument("--category", "-c", help="Category (default: Other)")
    p_append.add_argument("--question", "-q", help="Question text")

    p_update = sub.add_parser("update", help="Update an existing question")
    p_update.add_argument("id", help="Question ID")
    p_update.add_argument("--question", "-q", help="New question/phenomenon text (overwrites 现象/需求)")
    p_update.add_argument("--status", "-s", help="New status (Pending, 已解决待验证, 已验证, WontFix, Unresolved)")
    p_update.add_argument("--root-cause", "-r", help="Root cause analysis")
    p_update.add_argument("--answer", "-a", help="Solution steps")
    p_update.add_argument("--files", "-f", help="Files changed table (| File | Change |)")

    p_next = sub.add_parser("next-id", help="Print next available ID")

    sub.add_parser("format", help="Validate and reformat QA.md")

    args = parser.parse_args()

    commands = {
        "summary": cmd_summary,
        "get": cmd_get,
        "append": cmd_append,
        "update": cmd_update,
        "next-id": cmd_next_id,
        "format": cmd_format,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
