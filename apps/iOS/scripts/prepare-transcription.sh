#!/usr/bin/env bash
set -euo pipefail

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$apple_root/../../packages/heytim-transcription/scripts/prepare-apple.sh" apple
