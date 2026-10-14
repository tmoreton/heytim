#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'HeyTim Decider preparation requires an Apple Silicon Mac.' >&2
  exit 1
fi
command -v uv >/dev/null || { echo 'Install uv to prepare the bundled Decider runtime.' >&2; exit 1; }
runtime_root="$package_root/.runtime"
mkdir -p "$runtime_root"
uv python install --no-bin --install-dir "$runtime_root/python" 3.12.12
python_root="$runtime_root/python/cpython-3.12.12-macos-aarch64-none"
python="$python_root/bin/python3.12"
if [[ ! -x "$python" ]]; then
  echo "Standalone Python is missing: $python" >&2
  exit 1
fi
requirements="$package_root/requirements.lock"
[[ -f "$requirements" ]] || { echo 'Missing pinned requirements.lock.' >&2; exit 1; }
lock_hash="$(
  { shasum -a 256 "$requirements"; printf '%s\n' 'cpython-3.12.12-macos14-arm64'; } \
    | shasum -a 256 | awk '{print $1}'
)"
if [[ ! -f "$runtime_root/requirements.sha256" || "$(cat "$runtime_root/requirements.sha256")" != "$lock_hash" ]]; then
  MACOSX_DEPLOYMENT_TARGET=14.0 uv pip sync --python "$python" \
    --python-platform aarch64-apple-darwin --python-version 3.12.12 \
    --target "$python_root/lib/python3.12/site-packages" \
    --require-hashes --link-mode copy "$requirements"
  printf '%s\n' "$lock_hash" > "$runtime_root/requirements.sha256"
fi
"$python" -c 'import torch, mlx.core, strands_decider; print("Decider runtime ready", torch.__version__)'
printf '%s\n' "$python_root"
