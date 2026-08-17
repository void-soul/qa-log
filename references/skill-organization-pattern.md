# Skill Organization Pattern

This document captures the skill organization pattern used for qa-log and similar multi-component skills.

## Structure

Class-level skills should have a flat structure with sub-skills nested in a `skills/` directory:

```
~/.agents/skills/<skill-name>/
├── SKILL.md                    # Main entry point (thin, ~50 lines)
├── scripts/                    # Tooling/scripts
│   └── <tool>.py
├── references/                 # Reference docs
│   └── <topic>.md
└── skills/                     # Sub-skills (NEVER separate top-level dirs)
    ├── sub-skill-a.md
    ├── sub-skill-b.md
    └── sub-skill-c.md
```

## Rules

1. **One directory per skill class** — All sub-skills live under the main skill's directory
2. **No separate top-level directories** — Don't create `skill-a/`, `skill-b/` separately
3. **Nested access pattern** — Sub-skills are accessed via `parent/skills/sub-skill`
4. **Sync to Hermes** — Copy the entire directory structure to Hermes' skills folder

## Example

For qa-log:
```
~/.agents/skills/qa-log/
├── SKILL.md                    # Main docs
├── scripts/qa_tool.py
└── skills/
    ├── add-question.md
    ├── check.md
    ├── fill-solution.md
    └── format-doc.md
```

Hermes loads from:
```
~/AppData/Local/hermes/skills/software-development/qa-log/
├── SKILL.md
├── scripts/qa_tool.py
└── skills/
    ├── add-question.md
    ├── check.md
    ├── fill-solution.md
    └── format-doc.md
```

## Why This Pattern?

1. **Token efficiency** — Main SKILL.md is thin (~50 lines), sub-skills loaded on-demand
2. **Clear hierarchy** — Parent-child relationship is obvious from directory structure
3. **Easy maintenance** — All related files in one place
4. **No redundancy** — No duplicate directories or scattered sub-skills

## Migration Checklist

When restructuring skills:
- [ ] Move all sub-skills into parent's `skills/` directory
- [ ] Delete separate top-level sub-skill directories
- [ ] Update all `skill_view` calls to use nested paths
- [ ] Sync to Hermes' skills directory
- [ ] Verify all sub-skills load correctly
