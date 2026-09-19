#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
prune_archives=false

case "${1:-}" in
  "") ;;
  --archives) prune_archives=true ;;
  *)
    printf 'Usage: %s [--archives]\n' "$0" >&2
    exit 2
    ;;
esac

generated_paths=(
  "$repository_root/.pytest_cache"
  "$repository_root/.ruff_cache"
  "$repository_root/agentcore/.cache"
  "$repository_root/agentcore/cdk/cdk.out"
  "$repository_root/agentcore/cdk/dist"
  "$repository_root/apps/website/dist"
  "$repository_root/apps/website/public/catalog.json"
  "$repository_root/apps/website/public/skills"
  "$repository_root/apps/website/public/tools"
  "$repository_root/apps/website/public/bots"
  "$repository_root/packages/heytim-transcription/.build"
  "$repository_root/packages/heytim-transcription/.swiftpm"
  "$repository_root/services/runtime/.pytest_cache"
  "$repository_root/services/runtime/.ruff_cache"
  "$repository_root/services/runtime/evals/results"
  "$repository_root/services/API/.amplify"
)

python3 "$repository_root/services/runtime/scripts/codezip.py" clean --apply

for generated_path in "${generated_paths[@]}"; do
  if [[ -e "$generated_path" ]]; then
    rm -rf -- "$generated_path"
    printf 'Removed %s\n' "${generated_path#"$repository_root/"}"
  fi
done

find "$repository_root" -name .DS_Store -type f -delete

if [[ "$prune_archives" == true ]]; then
  archive_root="$repository_root/apps/iOS/Archives"
  if [[ -d "$archive_root" ]]; then
    for platform in iOS macOS; do
      latest_archive="$(find "$archive_root" -maxdepth 1 -type d \
        -name "HeyTim-$platform-*.xcarchive" -print | sort | tail -n 1)"
      while IFS= read -r archive; do
        [[ -n "$archive" && "$archive" != "$latest_archive" ]] || continue
        rm -rf -- "$archive"
        printf 'Removed %s\n' "${archive#"$repository_root/"}"
      done < <(find "$archive_root" -maxdepth 1 -type d \
        -name "HeyTim-$platform-*.xcarchive" -print | sort)
    done
  fi
fi

printf 'Generated outputs removed. Dependencies, virtual environments, and prepared transcription assets were preserved.\n'
if [[ "$prune_archives" == true ]]; then
  printf 'Older Apple archives were removed; the newest iOS and macOS archives were retained.\n'
fi
