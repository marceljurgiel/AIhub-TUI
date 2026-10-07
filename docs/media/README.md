# Demo media

The GIFs and screenshots in the main README are recorded with
[VHS](https://github.com/charmbracelet/vhs) from the scripts in `tapes/`,
inside a container with a demo user **alex**. The demo user has a tiny
project in `seed/demo` and a few memories in `seed/demo-memory.md`. Nothing
from your own machine ends up in the frames.

```bash
OLLAMA_SERVER=192.0.2.10 docs/media/record.sh            # all tapes
OLLAMA_SERVER=192.0.2.10 docs/media/record.sh chat agent # some
```

- The Ollama server appears as `gpu-box.lan` in the recordings.
- `install.tape` serves `install.sh` and the release from your checkout,
  so it works before a release exists. It speeds through the downloads
  with a cut.
- `windows.png` is a Windows 11 screenshot, taken by hand.

Look through the frames before committing new media, for example with
`ffmpeg -i chat.gif -vf "fps=1/2,tile=3x3" sheet.png`.
