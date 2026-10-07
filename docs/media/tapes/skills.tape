# AIhub demo — write a skill in one sentence, then use it. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/skills.gif
Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font Mono"
Set FontSize 16
Set Width 1400
Set Height 840
Set Padding 10
Set Framerate 20
Set TypingSpeed 40ms
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
Tab
Sleep 600ms
Type "k"
Wait+Screen@30s /code-review/
Sleep 2s
Type "n"
Sleep 1.5s
Type "Explain a Python file to a beginner: what it does, then each function in one line"
Sleep 800ms
Enter
Sleep 2.5s
# The model writes the draft — cut.
Hide
Wait+Screen@120s /discard/
Show
Sleep 4s
Screenshot out/skills.png
Enter
Wait+Screen@30s /Saved/
Sleep 2.5s
Enter
Sleep 1.5s
Type "inventory.py"
Sleep 800ms
Enter
Wait+Screen@20s /streaming/
Wait+Screen@180s /Message AIhub/
Sleep 5s
