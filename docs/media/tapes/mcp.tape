# AIhub demo — MCP servers in one click. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/mcp.gif
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
Tab
Sleep 800ms
Type "c"
Sleep 2.5s
Type "a"
Sleep 3s
Screenshot out/mcp.png
Down 2
Sleep 1.2s
Down 2
Sleep 1.2s
Up 4
Sleep 1s
Enter
Sleep 3.5s
Escape
Sleep 1s
