# AIhub demo — a vision model reads a pasted image. Recorded with VHS
# (https://github.com/charmbracelet/vhs); see docs/media/README.md to re-record.
# Needs a vision model as the chat model: MODEL=gemma4:cloud record.sh vision
Output out/vision.gif
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
Wait+Screen@60s /gemma4/
Wait+Screen@60s /Message AIhub/
Sleep 1s
# The model picker, filtered to this model (the full list is the recording
# server's own): it can see — "vision".
Ctrl+O
Wait+Screen@60s /can do/
Type "/"
Sleep 300ms
Type "gemma4:cloud"
Sleep 1.5s
Show
Sleep 3s
# Enter picks it (Esc would first clear the filter and show the full list).
Enter
Sleep 1.5s
# An image path and Enter: it becomes an attachment (as a dragged-in file
# does; VHS can't paste into the container's terminal).
Type "~/Pictures/sales-week41.png"
Sleep 500ms
Enter
Sleep 2.5s
Type "What does this chart show? Which item sold the most, and which the least?"
Sleep 600ms
Enter
Wait+Screen@120s /tok\/s/
Sleep 5s
Screenshot out/vision.png
Sleep 1s
