#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_repository="tmoreton/frog-bots"
mode="${1:---dry-run}"
if [[ "$mode" != --apply && "$mode" != --dry-run ]] || (( $# > 1 )); then
  echo "Usage: $0 [--dry-run|--apply]" >&2
  exit 2
fi

"$repository_root/scripts/assert-release-ready.sh"
"$repository_root/scripts/verify.sh" application
source_revision="$(git -C "$repository_root" rev-parse HEAD)"
if [[ "$mode" == --dry-run ]]; then
  echo "Verified website $source_revision. Would publish only apps/website/dist to $target_repository:gh-pages."
  exit 0
fi

# The public repository is an artifact mirror, not a second maintained source.
# main and all historical catalog tags are untouched.
gh auth status >/dev/null
staging="$(mktemp -d /tmp/frogbot-website-publish.XXXXXX)"
checkout="$staging/checkout"
git clone --quiet --no-checkout --filter=blob:none "https://github.com/$target_repository.git" "$checkout"
if git -C "$checkout" ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git -C "$checkout" fetch --quiet origin gh-pages
  git -C "$checkout" switch --quiet -c gh-pages FETCH_HEAD
else
  git -C "$checkout" switch --quiet --orphan gh-pages
fi
rsync -a --delete --exclude .git "$repository_root/apps/website/dist/" "$checkout/"
git -C "$checkout" add --all
if ! git -C "$checkout" diff --cached --quiet; then
  git -C "$checkout" -c user.name='FroggyBot Publisher' -c user.email='tmoreton89@gmail.com' \
    commit -m "Publish website from frogbot $source_revision"
  git -C "$checkout" push origin HEAD:gh-pages
fi
# Keep the existing domain and HTTPS settings; switch only the build source.
gh api --method PUT "repos/$target_repository/pages" \
  -f build_type=legacy -f 'source[branch]=gh-pages' -f 'source[path]=/' >/dev/null
echo "Published website source $source_revision to GitHub Pages. Check Pages completion before announcing it live."
echo "Recoverable publication checkout: $checkout"
