# AIhub demo — AIhub learns from the conversation. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/memory.gif
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
Type "Quick update: I switched from Python to Rust last month. Any tip for a first CLI tool?"
Sleep 800ms
Enter
Wait+Screen@20s /streaming/
Wait+Screen@180s /Message AIhub/
Sleep 2.5s
# Learning runs in the background after the reply — cut.
Hide
Wait+Screen@180s /Remembered/
Show
Sleep 4s
Screenshot out/memory-learned.png
Ctrl+E
Wait+Screen@20s /Rust/
Sleep 4s
Screenshot out/memory.png
Escape
Sleep 1s
Ctrl+N
Sleep 1.5s
Type "Which language am I using these days? One line."
Sleep 600ms
Enter
Wait+Screen@20s /streaming/
Wait+Screen@120s /Message AIhub/
Sleep 4s
