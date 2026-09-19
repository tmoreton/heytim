#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---dry-run}"
if [[ "$mode" != --apply && "$mode" != --dry-run ]] || (( $# > 1 )); then
  echo "Usage: $0 [--dry-run|--apply]" >&2
  exit 2
fi

"$repository_root/scripts/assert-release-ready.sh"
"$repository_root/scripts/verify.sh" application
source_revision="$(git -C "$repository_root" rev-parse HEAD)"
if [[ "$mode" == --dry-run ]]; then
  echo "Verified website $source_revision. This script would queue the monorepo's GitHub Pages workflow for heytim.ai."
  exit 0
fi

gh auth status >/dev/null
remote_revision="$(git -C "$repository_root" ls-remote origin refs/heads/main | cut -f1)"
if [[ "$source_revision" != "$remote_revision" ]]; then
  echo "Push $source_revision to origin/main before publishing it." >&2
  exit 1
fi
gh workflow run pages.yml --repo tmoreton/heytim --ref main
echo "Queued the heytim.ai Pages workflow for $source_revision."
