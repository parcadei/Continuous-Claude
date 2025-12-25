---
name: compound-learnings
description: Transform session learnings into permanent capabilities (skills, rules, agents). Use when asked to "improve setup", "learn from sessions", "compound learnings", or "what patterns should become skills".
allowed-tools: [Read, Glob, Grep, Write, Edit, Bash, AskUserQuestion]
---

# Compound Learnings

Transform ephemeral session learnings into permanent, compounding capabilities.

## When to Use

- "What should I learn from recent sessions?"
- "Improve my setup based on recent work"
- "Turn learnings into skills/rules"
- "What patterns should become permanent?"
- "Compound my learnings"

## Process

### Step 1: Gather Learnings

```bash
# List learnings (most recent first)
ls -t $CLAUDE_PROJECT_DIR/.claude/cache/learnings/*.md | head -20

# Count total
ls $CLAUDE_PROJECT_DIR/.claude/cache/learnings/*.md | wc -l
```

Read the most recent 5-10 files (or specify a date range).

### Step 2: Extract Patterns (Structured)

For each learnings file, extract entries from these specific sections:

| Section Header | What to Extract |
|----------------|-----------------|
| `## Patterns` or `Reusable techniques` | Direct candidates for rules |
| `**Takeaway:**` or `**Actionable takeaway:**` | Decision heuristics |
| `## What Worked` | Success patterns |
| `## What Failed` | Anti-patterns (invert to rules) |
| `## Key Decisions` | Design principles |

Build a frequency table as you go:

```markdown
| Pattern | Sessions | Category |
|---------|----------|----------|
| "Check artifacts before editing" | abc, def, ghi | debugging |
| "Pass IDs explicitly" | abc, def, ghi, jkl | reliability |
```

### Step 2b: Consolidate Similar Patterns

Before counting, merge patterns that express the same principle:

**Example consolidation:**
- "Artifact-first debugging"
- "Verify hook output by inspecting files"
- "Filesystem-first debugging"
→ All express: **"Observe outputs before editing code"**

Use the most general formulation. Update the frequency table.

### Step 3: Detect Meta-Patterns

**Critical step:** Look at what the learnings cluster around.

If >50% of patterns relate to one topic (e.g., "hooks", "tracing", "async"):
→ That topic may need a **dedicated skill** rather than multiple rules
→ One skill compounds better than five rules

Ask yourself: *"Is there a skill that would make all these rules unnecessary?"*

### Step 4: Categorize (Decision Tree)

For each pattern, determine artifact type:

```
Is it a sequence of commands/steps?
  → YES → SKILL (executable > declarative)
  → NO ↓

Should it run automatically on an event (SessionEnd, PostToolUse, etc.)?
  → YES → HOOK (automatic > manual)
  → NO ↓

Is it "when X, do Y" or "never do X"?
  → YES → RULE
  → NO ↓

Does it enhance an existing agent workflow?
  → YES → AGENT UPDATE
  → NO → Skip (not worth capturing)
```

**Artifact Type Examples:**

| Pattern | Type | Why |
|---------|------|-----|
| "Run linting before commit" | Hook (PreToolUse) | Automatic gate |
| "Extract learnings on session end" | Hook (SessionEnd) | Automatic trigger |
| "Debug hooks step by step" | Skill | Manual sequence |
| "Always pass IDs explicitly" | Rule | Heuristic |

### Step 5: Apply Signal Thresholds

| Occurrences | Action |
|-------------|--------|
| 1 | Note but skip (unless critical failure) |
| 2 | Consider - present to user |
| 3+ | Strong signal - recommend creation |
| 4+ | Definitely create |

### Step 6: Propose Artifacts

Present each proposal in this format:

```markdown
---

## Pattern: [Generalized Name]

**Signal:** [N] sessions ([list session IDs])

**Category:** [debugging / reliability / workflow / etc.]

**Artifact Type:** Rule / Skill / Agent Update

**Rationale:** [Why this artifact type, why worth creating]

**Draft Content:**
\`\`\`markdown
[Actual content that would be written to file]
\`\`\`

**File:** `.claude/rules/[name].md` or `.claude/skills/[name]/SKILL.md`

---
```

Use `AskUserQuestion` to get approval for each artifact (or batch approval).

### Step 7: Create Approved Artifacts

#### For Rules:
```bash
# Write to rules directory
cat > $CLAUDE_PROJECT_DIR/.claude/rules/<name>.md << 'EOF'
# Rule Name

[Context: why this rule exists, based on N sessions]

## Pattern
[The reusable principle]

## DO
- [Concrete action]

## DON'T
- [Anti-pattern]

## Source Sessions
- [session-id-1]: [what happened]
- [session-id-2]: [what happened]
EOF
```

#### For Skills:
Create `.claude/skills/<name>/SKILL.md` with:
- Frontmatter (name, description, allowed-tools)
- When to Use
- Step-by-step instructions (executable)
- Examples from the learnings

Add triggers to `skill-rules.json` if appropriate.

#### For Hooks:
Create shell wrapper + TypeScript handler:

```bash
# Shell wrapper
cat > $CLAUDE_PROJECT_DIR/.claude/hooks/<name>.sh << 'EOF'
#!/bin/bash
set -e
cd "$CLAUDE_PROJECT_DIR/.claude/hooks"
cat | node dist/<name>.mjs
EOF
chmod +x $CLAUDE_PROJECT_DIR/.claude/hooks/<name>.sh
```

Then create `src/<name>.ts`, build with esbuild, and register in `settings.json`:

```json
{
  "hooks": {
    "EventName": [{
      "hooks": [{
        "type": "command",
        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.sh"
      }]
    }]
  }
}
```

#### For Agent Updates:
Edit existing agent in `.claude/agents/<name>.md` to add the learned capability.

### Step 8: Summary Report

```markdown
## Compounding Complete

**Learnings Analyzed:** [N] sessions
**Patterns Found:** [M]
**Artifacts Created:** [K]

### Created:
- Rule: `explicit-identity.md` - Pass IDs explicitly across boundaries
- Skill: `debug-hooks` - Hook debugging workflow

### Skipped (insufficient signal):
- "Pattern X" (1 occurrence)

**Your setup is now permanently improved.**
```

## Quality Checks

Before creating any artifact:

1. **Is it general enough?** Would it apply in other projects?
2. **Is it specific enough?** Does it give concrete guidance?
3. **Does it already exist?** Check `.claude/rules/` and `.claude/skills/` first
4. **Is it the right type?** Sequences → skills, heuristics → rules

## Files Reference

- Learnings: `.claude/cache/learnings/*.md`
- Skills: `.claude/skills/<name>/SKILL.md`
- Rules: `.claude/rules/<name>.md`
- Hooks: `.claude/hooks/<name>.sh` + `src/<name>.ts` + `dist/<name>.mjs`
- Agents: `.claude/agents/<name>.md`
- Skill triggers: `.claude/skills/skill-rules.json`
- Hook registration: `.claude/settings.json` → `hooks` section
