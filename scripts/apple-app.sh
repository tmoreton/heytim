#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apple_root="$repository_root/apps/iOS"

usage() {
  cat <<'EOF'
HeyTim Apple app

Usage:
  ./scripts/apple-app.sh open
  ./scripts/apple-app.sh build
  ./scripts/apple-app.sh run <ios|macos>
  ./scripts/apple-app.sh verify
  APPLE_TEAM_ID=TEAMID ./scripts/apple-app.sh archive [--dry-run] <ios|macos>
  APPLE_TEAM_ID=TEAMID ./scripts/apple-app.sh testflight [--dry-run] ios
  APPLE_TEAM_ID=TEAMID ./scripts/apple-app.sh distribute-macos [--dry-run]

The SwiftUI project is the only supported local Apple build source. iPhone ships
through TestFlight; Mac ships as a notarized direct download with Sparkle updates.
apps/website is the public Vite marketing site, not a native release target.
EOF
}

command="${1:-}"
if [[ -z "$command" ]]; then
  usage
  exit 0
fi
shift

case "$command" in
  open)
    if [[ $# -ne 0 ]]; then
      usage >&2
      exit 2
    fi
    open "$apple_root/HeyTimApple.xcodeproj"
    ;;
  build)
    if [[ $# -ne 0 ]]; then
      usage >&2
      exit 2
    fi
    exec "$apple_root/scripts/run.sh" --build-only all
    ;;
  run)
    exec "$apple_root/scripts/run.sh" "$@"
    ;;
  verify|test)
    if [[ $# -ne 0 ]]; then
      usage >&2
      exit 2
    fi
    exec "$apple_root/scripts/verify.sh"
    ;;
  archive)
    exec "$apple_root/scripts/archive.sh" "$@"
    ;;
  testflight)
    exec "$apple_root/scripts/testflight.sh" "$@"
    ;;
  distribute-macos)
    exec "$apple_root/scripts/distribute-macos.sh" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown Apple app command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
