# AIhub demo — a shell beside the chat. Recorded with VHS
# (https://github.com/charmbracelet/vhs); see docs/media/README.md to re-record.
Output out/terminal.gif
Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font Mono"
Set FontSize 16
Set Width 1400
Set Height 840
Set Padding 10
Set Framerate 12
Set TypingSpeed 45ms
Hide
Type "export PATH=$HOME/.local/bin:$PATH PS1='$ '; cd ~/demo; clear"
Enter
Type "aihub"
Enter
Wait+Screen@60s /nemotron/
Wait+Screen@60s /Message AIhub/
Sleep 1s
Show
Sleep 1.5s
# Ask in the chat…
Type "What does low_stock in inventory.py return? One sentence."
Sleep 500ms
Enter
# The reply is done when the header says so (tok/s shows while it streams).
Wait+Screen@120s /active session/
Sleep 2.5s
# …and open a shell beside it (F8; VHS has no F-keys, so /terminal).
Type "/terminal"
Sleep 600ms
Enter
Sleep 2.5s
Type "python -m pytest -q tests"
Sleep 400ms
Enter
Sleep 4s
Type "grep -n 'def ' inventory.py"
Sleep 400ms
Enter
Sleep 3.5s
Screenshot out/terminal.png
Sleep 1s
