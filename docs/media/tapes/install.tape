# AIhub demo — the one-line installer. Recorded with VHS
# (https://github.com/charmbracelet/vhs); see docs/media/README.md.
Output out/install.gif
Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font Mono"
Set FontSize 16
Set Width 1400
Set Height 840
Set Padding 10
Set Framerate 20
Set TypingSpeed 35ms
# Off camera: serve install.sh and the release from the local build, so the
# demo works before a release exists. Everything else is the real installer.
Hide
Type `export PATH=$HOME/.local/bin:$PATH PS1="$ " AIHUB_SOURCE=/pkg/aihub.tar.gz; curl() { case "$*" in *install.sh*) cat /pkg/install.sh;; *) command curl "$@";; esac; }; clear`
Enter
Show
Sleep 800ms
Type "curl -fsSL https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.sh | bash"
Sleep 800ms
Enter
Sleep 4s
# Downloads (uv, Python, Bun) — cut.
Hide
Wait+Screen@300s /Choice \[L\/s\/k\]/
Show
Sleep 2.5s
Type "s"
Sleep 500ms
Enter
Sleep 1.5s
Type "gpu-box.lan"
Sleep 600ms
Enter
Wait+Screen@120s /is installed/
Sleep 3.5s
Screenshot out/install.png
Type "aihub"
Sleep 500ms
Enter
Wait+Screen@60s /CONNECTED/
Wait+Screen@60s /Message AIhub/
Sleep 3s
