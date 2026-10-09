#!/usr/bin/env bash
# Re-record the README media from the committed code.
#
#   OLLAMA_SERVER=<address of an Ollama server> docs/media/record.sh [tape …]
#
# Needs podman. The server is reached as "gpu-box.lan" inside the recording,
# so its real address never shows. Tapes: hero install chat agent models mcp skills memory theme
# knowledge schedule terminal vision (vision needs MODEL=gemma4:cloud or another vision model).
# MODEL=<name> picks the chat model (default nemotron-3-ultra:cloud).
set -euo pipefail
: "${OLLAMA_SERVER:?set OLLAMA_SERVER to your Ollama server, e.g. OLLAMA_SERVER=192.0.2.10}"
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
mkdir -p "$work/pkg" "$work/out"; chmod 777 "$work/out"

git -C "$root" archive --prefix=AIhub-TUI-main/ -o "$work/pkg/aihub.tar.gz" HEAD
cp "$root/install.sh" "$work/pkg/"
cp -r "$here/seed" "$here/Containerfile.base" "$here/Containerfile.demo" "$work/"
podman build -q -t aihub-vhs-base -f "$work/Containerfile.base" "$work" >/dev/null
podman build -q -t aihub-vhs-demo --build-arg "MODEL=${MODEL:-nemotron-3-ultra:cloud}" \
  -f "$work/Containerfile.demo" "$work" >/dev/null

cp -r "$here/tapes" "$work/tapes"
failed=""
for tape in "${@:-hero install chat agent models mcp skills memory theme knowledge schedule terminal}"; do
  for t in $tape; do
    image=aihub-vhs-demo; [ "$t" = install ] && image=aihub-vhs-base
    # A long tape's render can run out of memory or a model can answer
    # oddly: one more try, then carry on with the rest.
    for attempt in 1 2; do
      echo "recording $t (try $attempt)"
      if podman run --rm --userns=keep-id --user alex -e HOME=/home/alex -w /vhs --hostname demo-pc \
           --add-host "gpu-box.lan:$OLLAMA_SERVER" \
           -v "$work/tapes:/vhs:Z" -v "$work/out:/vhs/out:Z" "$image" "/vhs/$t.tape"; then
        continue 2
      fi
    done
    failed="$failed $t"
  done
done
# hero.tape leaves one screenshot per colour combination: one looping GIF.
if [ -e "$work/out/hero-00.png" ]; then
  frames=$(cd "$work/out" && ls hero-[0-9][0-9].png | sort)
  { for f in $frames; do printf "file '/out/%s'\nduration 0.9\n" "$f"; done
    printf "file '/out/%s'\n" "$(echo "$frames" | tail -1)"; } > "$work/out/hero.txt"
  podman run --rm -v "$work/out:/out:Z" --entrypoint ffmpeg aihub-vhs-base -v error -y \
    -f concat -safe 0 -i /out/hero.txt -loop 0 \
    -vf "scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=single[p];[b][p]paletteuse=new=1:dither=none" \
    /out/hero.gif
  rm -f "$work/out"/hero-[0-9][0-9].png "$work/out/hero-raw.gif" "$work/out/hero.txt"
fi
# Screenshots the tapes take along the way that the README doesn't use.
rm -f "$work/out/agent-permission.png" "$work/out"/theme-*.png
cp "$work/out/"* "$here/" 2>/dev/null || true
if [ -n "$failed" ]; then
  echo "done, except:$failed — run again with just those"
  exit 1
fi
echo "done — check the frames before committing (no real names, paths or addresses)"
