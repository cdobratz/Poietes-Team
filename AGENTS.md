# Agent instructions

Trial rules for coding agents that edit this repository. Prompts on the specialist agents stay in force. This file does not replace them.

## Precedence

Security and approval behavior already in the code wins over a shorter edit.

- Paths from a task or from model output are untrusted. Keep writes and filesystem work inside the project or workspace root (`tools/safe_paths.py`, `FilesystemAgent`).
- Keep git credentials out of URLs, command arguments, and `.git/config` (`tools/git_tools.py`).
- When `workspace.approval_required` is on, a non-interactive run must not write files, and a skipped write is not a success.
- Leave Bandit, Semgrep, and Safety available to `SecurityAgent` when they are enabled.

Saying what you did not check does not excuse skipping the controls above.

## Rules

1. Read the code, tests, and config the task touches before you edit.
2. Reuse a helper or pattern that is already in this repository, the same way nearby code does.
3. Prefer the Python standard library or a package this repository already installs.
4. Ship the smallest change that finishes the task. Leave out options and files that were not requested.
5. Add one small test when the new logic branches, parses input, or touches security. Docs and comments need none.
6. Keep validation, security checks, and error handling that prevents data loss.
7. End with one or two lines on what you did not run or did not check, and the risk that leaves.
