# AIhub demo — the model picker. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/models.gif
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
# Straight to "Fit": the Installed tab would show the recording server's own
# model list, which isn't demo data.
Ctrl+O
Wait+Screen@60s /GB/
Type "2"
Wait+Screen@120s /fit for server/
Show
Sleep 3.5s
Screenshot out/models.png
Type "3"
Hide
Wait+Screen@60s /search the Ollama library/
Sleep 1s
Show
Sleep 2.5s
Down 3
Sleep 1.5s
Type "5"
Sleep 3.5s
Escape
Sleep 1s
