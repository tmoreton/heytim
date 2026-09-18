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
  echo "Verified website $source_revision. Would publish apps/website/dist to tmoreton/heytim-web:main and tmoreton/heytim-bots:gh-pages."
  exit 0
fi

# Both public repositories are artifact mirrors, not separate maintained sources.
# The bot repository's main branch and historical catalog tags are untouched.
gh auth status >/dev/null
staging="$(mktemp -d /tmp/heytim-website-publish.XXXXXX)"

publish_mirror() {
  local target_repository="$1" branch="$2" domain="$3"
  local checkout="$staging/${target_repository##*/}"
  git clone --quiet --filter=blob:none --single-branch --branch "$branch" \
    "https://github.com/$target_repository.git" "$checkout"
  rsync -a --delete --exclude .git "$repository_root/apps/website/dist/" "$checkout/"
  printf '%s\n' "$domain" > "$checkout/CNAME"
  git -C "$checkout" add --all
  if ! git -C "$checkout" diff --cached --quiet; then
    git -C "$checkout" -c user.name='HeyTim Publisher' -c user.email='tmoreton89@gmail.com' \
      commit -m "Publish website from HeyTim $source_revision"
    git -C "$checkout" push origin "HEAD:$branch"
  fi
  gh api --method PUT "repos/$target_repository/pages" \
    -f build_type=legacy -f "source[branch]=$branch" -f 'source[path]=/' >/dev/null
  gh api --method POST "repos/$target_repository/pages/builds" >/dev/null
  echo "Published $domain from HeyTim $source_revision. Recoverable checkout: $checkout"
}

publish_mirror tmoreton/heytim-web main heytim.ai
publish_mirror tmoreton/heytim-bots gh-pages app.heytim.ai
echo "Check both Pages builds before announcing the website live."
