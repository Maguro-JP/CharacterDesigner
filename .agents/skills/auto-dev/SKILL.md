---
name: auto-dev
description: Use when the user asks to continue autonomously, fix the project, make progress without repeated confirmation, or run a multi-step development task. Prioritize verified fixes, keep working across independent tasks, and report only real outcomes.
---

# Autonomous development

- Start from the user's latest instruction and the repository's open P0/P1 issues. Prefer the smallest user-visible blocker with a reproducible path.
- Do not ask routine questions. Choose reversible defaults and document them. Stop only for decisions involving destructive data changes, credentials, spending, public release, production deployment, or a genuinely blocking ambiguity.
- Work in short cycles: inspect → reproduce/test → fix → verify → inspect diff → record result.
- Fix one failure at a time. Do not create bugs and then spend cycles repairing those self-created bugs.
- After one task is verified, continue to the next independent P0/P1 task. Do not stop merely because one issue is blocked.
- Keep CI usage economical: run focused local tests first; trigger only the workflow that proves the changed behavior.
- Do not merge, release, or alter production settings unless explicitly authorized.
- Persist progress in issue comments or concise repository progress notes when the work spans sessions.
- Report the exact commit/PR and test result. Clearly label anything not executed or not verified.
