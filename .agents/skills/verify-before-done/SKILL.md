---
name: verify-before-done
description: Use after code or configuration changes and before saying fixed, complete, working, passed, or ready. Requires executable evidence and honest incomplete-state reporting.
---

# Verify before done

1. Define the observable acceptance condition before editing.
2. Add or update a regression test that fails on the old behavior.
3. Run the focused test and inspect its complete exit status and relevant output.
4. Run the broader relevant suite or CI workflow when available.
5. Read the final diff and confirm only intended files changed.
6. Distinguish code written, test passed, CI passed, merged, released, and deployed. They are separate states.
7. If execution was unavailable, say so explicitly. Never infer a pass from static inspection or from a previous commit's CI result.
8. For drawing changes, verify both metadata/state and image output. A generated image with failed or missing inspection is incomplete, not successful.
