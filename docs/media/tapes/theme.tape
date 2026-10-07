# AIhub demo — themes and accent colours, previewed live. Recorded with VHS
# (https://github.com/charmbracelet/vhs); see docs/media/README.md to re-record.
Output out/theme.gif
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
Type "Name three Lisbon neighbourhoods with one **bold** word each, as a list."
Enter
Wait+Screen@20s /streaming/
Wait+Screen@120s /Message AIhub/
Sleep 1s
Show
Sleep 2s
Tab
Sleep 600ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 1.5s
Screenshot out/theme-aihub.png
Sleep 600ms
Down
Sleep 1.4s
Screenshot out/theme-tokyo-night.png
Sleep 600ms
Down
Sleep 1.4s
Down
Sleep 1.4s
Down
Sleep 1.4s
Down
Sleep 1.4s
Screenshot out/theme-gruvbox.png
Sleep 600ms
Down
Sleep 1.8s
Screenshot out/theme-light.png
Sleep 600ms
Up 5
Sleep 1.2s
Right
Sleep 1.2s
Right
Sleep 1.2s
Right
Sleep 1.2s
Right
Sleep 1.5s
Enter
Sleep 3s
Screenshot out/theme.png
Sleep 1s
