#!/usr/bin/env bash
set -euo pipefail
apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$apple_root/../../packages/heytim-decider/scripts/prepare-macos.sh"
