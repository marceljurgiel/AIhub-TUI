# Contributing to AIHub

Thank you for taking the time to contribute! ❤️

## Ways to Contribute

- 🐛 **Report bugs** — open an Issue with steps to reproduce
- 💡 **Suggest features** — open an Issue with the `enhancement` label
- 📝 **Improve documentation** — fix typos, add examples
- 🔧 **Submit a Pull Request** — see below

---

## Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/AIhub-TUI.git
cd AIhub-TUI

# 2. Engine (Python 3.10+; uv is easiest)
uv venv --python 3.12
uv pip install -e ".[dev]"

# 3. Terminal app (Bun)
cd app && bun install && cd ..

# 4. Run the tests
.venv/bin/python -m pytest
cd app && bun test && bunx tsc --noEmit
```

Run the app from the checkout with `cd app && bun run start`.

Never commit personal data: `tests/test_public_clean.py` fails on private
IP addresses, home paths and real-looking tokens. Use `192.0.2.x` and
`gpu-box.lan` in examples.

---

## Workflow

1. **Branch naming**
   - `feat/<short-description>` — new feature
   - `fix/<short-description>` — bug fix
   - `docs/<short-description>` — documentation only
   - `refactor/<short-description>` — code cleanup, no behaviour change

2. **Commit messages** — follow [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat: add Anthropic API support
   fix: correct VRAM parsing on Windows
   docs: update Windows installation steps
   ```

3. **Pull Requests**
   - Target the `main` branch
   - Include a clear description of what changed and why
   - Reference related Issues with `Closes #<number>`

---

## Code Style

- Follow **PEP 8**
- Add a **docstring** to every module, class, and public function
- Use `os.path.join()` for all file paths (cross-platform compatibility)
- TypeScript in `app/` follows the existing style; `bunx tsc --noEmit` must pass

---

## Adding a Model to the Registry

To add a new model, open `models_registry.json` and append an entry:

```json
{
  "name": "my-model",
  "type": "chat",
  "url": "my-model",
  "vram_required": 8,
  "size_gb": 4.5,
  "tags": ["General", "Code"],
  "description": "Short description of the model."
}
```

Valid types: `chat`, `image`, `video`
Valid tags: `General`, `Code`, `Reasoning`, `Documentation`, `Agentic`, `Agentic + Tool Calling`, `API`

---

## Reporting Bugs

Please include:
- OS and Python version (`python3 --version`)
- Full error traceback
- Steps to reproduce
- Expected vs actual behaviour
