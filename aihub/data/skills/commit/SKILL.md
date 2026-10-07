---
name: commit
description: Write a clear git commit message from the current changes and commit them. Use when the user asks to commit, or for a commit message.
---
1. Run `git status --short` and `git diff --staged` with run_terminal. If nothing is staged, show `git diff --stat` and ask which files to stage — never stage everything blindly.
2. Never stage files that look like secrets (.env, *.key, credentials) — warn the user instead.
3. Write the message:
   - first line: imperative mood, max 72 characters, no period ("Fix login timeout on slow networks");
   - blank line, then 1–4 short lines on WHY the change was made, if it isn't obvious;
   - follow the style of `git log --oneline -5` if the repository has one (e.g. "feat:" prefixes).
4. If the user only asked for a message, show it and stop. Otherwise commit with `git commit -m "<first line>" -m "<body>"`.
5. Report the commit hash and first line. Never push unless asked.
