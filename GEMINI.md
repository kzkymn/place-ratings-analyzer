# GEMINI.md

See `CLAUDE.md` for full project guidance (architecture, commands, known issues, conventions).
Detailed workflow skills are in `.agents/skills/`.

## Gemini's Role in This Project

Gemini acts as **QA reviewer**, not implementer. After Claude Code completes a task:

```bash
nohup bash -c 'agy --dangerously-skip-permissions -p "<review task>"' > review.log 2>&1 &
```

- CLI: `agy` (`--dangerously-skip-permissions` = auto-approve tools, `-p` = non-interactive prompt)
- Review focus: CLAUDE.md compliance, test coverage, correctness
- Output: flag issues found; Claude Code applies fixes
