# AIhub demo — a tool call that asks first. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/agent.gif
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
Type "Run the tests in this folder and tell me if they pass."
Sleep 600ms
Enter
Wait+Screen@90s /Permission required/
Sleep 2.5s
Screenshot out/agent-permission.png
Type "y"
Wait+Screen@180s /Message AIhub/
Sleep 3s
Screenshot out/agent.png
Sleep 2s
