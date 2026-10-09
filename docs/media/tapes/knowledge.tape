# AIhub demo — a knowledge base from your documents, then a chat that cites it. Recorded with VHS (https://github.com/charmbracelet/vhs);
# see docs/media/README.md to re-record.
Output out/knowledge.gif
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
# Knowledge (menu letter b): a new base from the shop handbook.
Tab
Sleep 800ms
Type "b"
Sleep 2s
Type "n"
Sleep 1s
Type "shop"
Sleep 500ms
Enter
Sleep 800ms
Type "Shipping, returns and stock rules"
Sleep 500ms
Enter
Sleep 800ms
Type "~/Documents/handbook"
Sleep 600ms
Enter
Wait+Screen@120s /shop: \d+ files/
Sleep 2.5s
Enter
Sleep 1.5s
Screenshot out/knowledge.png
Sleep 1s
Escape
Sleep 1s
# Use it in the chat; the answer cites the handbook.
Type "/kb shop"
Sleep 500ms
Enter
Sleep 1.5s
Type "A customer wants to send back a faulty kettle after three weeks. Can they, and who pays the postage?"
Sleep 600ms
Enter
Wait+Screen@120s /tok\/s/
Sleep 5s
