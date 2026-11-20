# CharacterDesigner — Codex project instructions

## Priority
- Follow the user's latest explicit instruction over repository conventions and agent assumptions.
- Work autonomously on reversible engineering tasks. Do not ask for approval for routine investigation, tests, refactors local to the fix, or changes on the current task branch.
- Do not claim a change works until the relevant tests or executable workflow have actually run and their result has been inspected.
- Never conceal uncertainty, skipped checks, failures, or incomplete output.

## Work loop
1. Read the current issue, branch state, recent changes, and the smallest relevant code path.
2. Reproduce the defect or write a failing regression test before changing behavior.
3. Make the smallest complete fix. Avoid unrelated refactors and speculative features.
4. Run focused tests first, then the relevant broader test suite. Inspect the diff after editing.
5. Record exact test results and remaining limitations. Keep incomplete drawing output explicitly marked incomplete.
6. Continue to the next independent P0/P1 task without waiting for user confirmation.

## CharacterDesigner quality rules
- A generated image is not a completed image. Completion requires all required phases to execute and their required inspections to pass.
- An inspection error, missing dependency, unreadable result, or unverified check is never a pass.
- A failed phase may retry only through a defined, bounded repair path. If no valid repair path remains, stop and save as incomplete; never silently advance.
- Preserve user-requested content. Do not add prompt details, attributes, or style preferences that the user did not request.
- Destructive image operations require before/after comparison and preservation of protected regions.
- Human UI operations and AI structured tools should share the same underlying implementation and validation contract.

## Git workflow
- Continue on the existing task branch unless it is unavailable or conflicts with the user's work.
- Do not rewrite history, force-push, merge, release, publish, or change production settings without explicit authorization.
- Keep commits focused. Do not create a PR just to report progress.
- Prefer targeted CI workflows; avoid unnecessary Actions runs.

## Skills
- Use relevant skills under `.agents/skills/` when their descriptions match the task.
- Claude-specific hooks and commands under `.claude/` are not automatically executable by Codex. Port their behavior to Codex-compatible instructions or scripts before relying on them.
