# Security

## Supported versions

Only the latest release gets fixes. Update with `aihub update`.

## Reporting a vulnerability

Please **don't** open a public issue for a security problem. Report it
privately instead:

1. Go to this repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe what you found, how to reproduce it, and what an attacker could
   do with it.

Only the maintainer sees the report and will answer as soon as possible. Once
a fix is released, the advisory is published with credit to you, unless you'd
rather stay anonymous.

## What AIhub does with your data

- AIhub runs on your machine and talks to the Ollama server you choose.
  Chats, memory, knowledge bases and settings stay in `~/.aihub`.
- Requests leave your network only when you pick a cloud model (Ollama Cloud,
  an API model) or use a connection (Gmail, GitHub…) — then they go to that
  service.
- Tokens for connections are stored in `~/.aihub` with permissions only you
  can read. Tools that change something (send, delete, write a file, run a
  command) ask you first, unless you set an agent to run on its own.
