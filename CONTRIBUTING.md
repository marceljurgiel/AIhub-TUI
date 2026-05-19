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
git clone https://github.com/YOUR_USERNAME/aihub.git
cd aihub

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\activate       # Windows

# 3. Install in editable mode with dev extras
pip install -e ".[dev]"
# or simply:
pip install -r requirements.txt
```

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
- Use `rich` for all terminal output — no bare `print()` calls in the TUI

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
