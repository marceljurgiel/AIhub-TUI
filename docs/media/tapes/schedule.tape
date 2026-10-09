# AIhub demo — a scheduled task, run now, and its result. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/schedule.gif
Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font Mono"
Set FontSize 16
Set Width 1400
Set Height 840
Set Padding 10
Set Framerate 20
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
# Schedule (menu letter j): a daily task for the coder agent.
Tab
Sleep 800ms
Type "j"
Sleep 2s
Type "n"
Sleep 1s
Type "todo-digest"
Sleep 500ms
Enter
Sleep 1.2s
Enter
Sleep 1s
Type "weekdays 09:00"
Sleep 500ms
Enter
Sleep 1s
Type "Read ~/demo/inventory.py and list its functions, one line each: name and what it does."
Sleep 800ms
Ctrl+S
Sleep 2s
Screenshot out/schedule.png
Sleep 1s
# Run it now instead of waiting for 09:00, then open the result.
Type "r"
Wait+Screen@180s /ok ·/
Sleep 2s
Enter
Sleep 4s
