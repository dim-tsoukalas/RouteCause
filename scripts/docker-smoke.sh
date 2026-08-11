#!/usr/bin/env bash
# Smoke test (macOS / Linux / WSL / CI): build the image and verify the
# pipeline end-to-end.
#   Usage:  ./scripts/docker-smoke.sh            # tag: routecause
#           ./scripts/docker-smoke.sh myimage
set -uo pipefail

IMAGE="${1:-routecause}"
fail=0
pass() { printf '  \033[32m[PASS]\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m[FAIL]\033[0m %s\n' "$1"; fail=1; }

echo "==> Building $IMAGE"
if docker build -t "$IMAGE" .; then pass "docker build"
else bad "docker build"; echo "Build failed; aborting."; exit 1; fi

echo "==> Flagship demo (offline, no key)"
out="$(docker run --rm "$IMAGE" 2>&1)"
if grep -q "Investigation: pakistan-youtube-2008" <<<"$out" \
   && grep -q "MOAS" <<<"$out" \
   && grep -q "208.65.153.0/24" <<<"$out"; then
  pass "default demo produced the MOAS finding"
else
  bad "default demo output missing expected markers"; tail -n 5 <<<"$out"
fi

echo "==> Second incident (rostelecom-2020)"
docker run --rm "$IMAGE" rostelecom-2020 --seek-contradictions >/dev/null 2>&1 \
  && pass "rostelecom-2020 ran" || bad "rostelecom-2020 failed"

echo "==> ask (offline retrieval)"
docker run --rm --entrypoint ask "$IMAGE" "how is a BGP AS_PATH loop detected?" >/dev/null 2>&1 \
  && pass "ask ran" || bad "ask failed"

echo "==> pytest suite"
docker run --rm --entrypoint pytest "$IMAGE" -q >/dev/null 2>&1 \
  && pass "pytest suite passed" || bad "pytest suite failed"

echo
if [ "$fail" -eq 0 ]; then
  printf '\033[32mAll smoke checks passed.\033[0m\n'
else
  printf '\033[31mSome smoke checks failed.\033[0m\n'; exit 1
fi
