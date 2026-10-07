# AIhub demo — the README's top image: one conversation in many colour
# combinations. Every frame is a screenshot (the picker is used off camera);
# docs/media/record.sh turns them into hero.gif. See docs/media/README.md.
Output out/hero-raw.gif
Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font Mono"
Set FontSize 16
Set Width 1400
Set Height 840
Set Padding 10
Set Framerate 10
Set TypingSpeed 40ms
Hide
# Let the shell start before typing into it.
Sleep 2s
Type "export PATH=$HOME/.local/bin:$PATH PS1='$ '; cd ~/demo; clear"
Enter
Type "aihub"
Enter
Wait+Screen@60s /nemotron/
Wait+Screen@60s /Message AIhub/
Sleep 1s
Type@15ms "Read inventory.py and explain it in three bullet points, each starting with a **bold** name."
Enter
Wait+Screen@20s /streaming/
Wait+Screen@180s /Message AIhub/
Sleep 1.5s
Show
Sleep 300ms
Screenshot out/hero-00.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-01.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-02.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-03.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-04.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-05.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-06.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Up 6
Sleep 300ms
Right 4
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-07.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Right 2
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-08.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Left 3
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-09.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Right 2
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-10.png
Sleep 600ms
Tab
Sleep 300ms
Type "t"
Wait+Screen@10s /Tokyo Night/
Sleep 300ms
Down 1
Sleep 300ms
Right 2
Sleep 300ms
Enter
Sleep 400ms
Escape
Sleep 800ms
Screenshot out/hero-11.png
Sleep 600ms
