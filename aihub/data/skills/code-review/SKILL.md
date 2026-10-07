---
name: code-review
description: Review code changes or a file for bugs, risky patterns and readability. Use when the user asks for a code review or to check their changes.
---
1. Find what to review: the files the user named, otherwise the current changes (`git diff` and `git diff --staged` via run_terminal).
2. Read enough surrounding code (read_file, search_files) to understand each change — don't judge a line without its context.
3. Look for, in this order:
   - bugs: wrong logic, off-by-one, unhandled errors or None, race conditions, resource leaks;
   - security: injected input in shell/SQL/paths, secrets in code, unsafe deserialization;
   - behaviour changes the author may not have intended;
   - readability: confusing names, dead code, duplicated logic.
4. Report findings most severe first, each as: `file:line` — the problem — a concrete fix. Skip style nitpicks unless asked.
5. If you find nothing important, say so in one line. Don't edit files unless the user asks.
