#!/usr/bin/env bash
# Full backup of this repository: git objects + everything GitHub holds that git does not.
#
# A `git clone` is NOT a backup. It copies the default branch's history and nothing else --
# no other branches' tips as such, no issues, no releases, no repository settings. If the
# repo ever has to be deleted and recreated (see docs/repo-hygiene.md), issues are the one
# thing that genuinely cannot be recovered from a local clone.
#
#   tools/backup_repo.sh [target-dir]        # default: ../package_pdf2anki-backup-<date>
#
# Requires: git. `gh` (authenticated) is optional -- without it you get the git mirror only,
# and the script says so instead of silently skipping.

set -uo pipefail

REPO_SLUG="${REPO_SLUG:-krausality/package_pdf2anki}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/../package_pdf2anki-backup-$STAMP}"

mkdir -p "$DEST" || { echo "[FATAL] cannot create $DEST"; exit 1; }
DEST="$(cd "$DEST" && pwd)"
echo "[INFO] backing up $REPO_SLUG -> $DEST"

fail=0

# --- 1. git: a mirror, not a clone -------------------------------------------------------
# --mirror takes every ref (all branches, all tags, notes) and keeps them as-is. Restoring
# is `git push --mirror` at a fresh remote.
echo "[1/4] git mirror"
if git clone --quiet --mirror "https://github.com/$REPO_SLUG.git" "$DEST/repo.git"; then
    echo "      $(git --git-dir="$DEST/repo.git" for-each-ref | wc -l) refs, $(du -sh "$DEST/repo.git" | cut -f1)"
else
    echo "      [FAIL] mirror clone failed"; fail=1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "[WARN] 'gh' not found -- issues, releases and settings NOT backed up."
    echo "       Install the GitHub CLI and rerun to get a complete backup."
    exit $fail
fi

# --- 2. issues (the part a clone cannot give you) ----------------------------------------
echo "[2/4] issues + comments"
if gh issue list --repo "$REPO_SLUG" --state all --limit 1000 \
      --json number,title,body,state,labels,assignees,milestone,createdAt,updatedAt,closedAt,author,url \
      > "$DEST/issues.json" 2>/dev/null; then
    n=$(grep -o '"number"' "$DEST/issues.json" | wc -l)
    echo "      $n issue(s)"
    # Comments are a separate endpoint; without them a restored issue loses the discussion.
    gh api "repos/$REPO_SLUG/issues/comments?per_page=100" --paginate \
        > "$DEST/issue-comments.json" 2>/dev/null \
        && echo "      comments saved" \
        || echo "      [WARN] could not fetch issue comments"
else
    echo "      [FAIL] could not fetch issues"; fail=1
fi

# --- 3. releases + their binary assets ---------------------------------------------------
echo "[3/4] releases"
if gh api "repos/$REPO_SLUG/releases" --paginate > "$DEST/releases.json" 2>/dev/null; then
    # grep -c exits 1 on zero matches, so `|| echo 0` would append a SECOND line and the
    # -gt test below would abort with "integer expression expected". Count via jq instead.
    n=$(gh api "repos/$REPO_SLUG/releases" --jq 'length' 2>/dev/null | head -1)
    n=${n:-0}
    echo "      $n release(s)"
    if [ "$n" -gt 0 ]; then
        mkdir -p "$DEST/release-assets"
        # Release assets are NOT in git. Losing them is losing them.
        gh release list --repo "$REPO_SLUG" --limit 100 2>/dev/null | cut -f3 | while read -r tag; do
            [ -n "$tag" ] && gh release download "$tag" --repo "$REPO_SLUG" \
                --dir "$DEST/release-assets/$tag" --clobber 2>/dev/null
        done
    fi
else
    echo "      [WARN] could not fetch releases"
fi

# --- 4. repository settings --------------------------------------------------------------
echo "[4/4] repository metadata"
gh api "repos/$REPO_SLUG" > "$DEST/repo-metadata.json" 2>/dev/null \
    && echo "      description, topics, visibility, default branch" \
    || echo "      [WARN] could not fetch metadata"
gh api "repos/$REPO_SLUG/labels?per_page=100" --paginate > "$DEST/labels.json" 2>/dev/null
gh api "repos/$REPO_SLUG/forks?per_page=100" --paginate > "$DEST/forks.json" 2>/dev/null

cat > "$DEST/RESTORE.md" <<EOF
# Restore

Backup of \`$REPO_SLUG\`, taken $STAMP.

## Git history

    gh repo create $REPO_SLUG --public
    cd repo.git
    git push --mirror https://github.com/$REPO_SLUG.git

\`--mirror\` restores every branch and tag exactly as they were.

## Issues

\`issues.json\` and \`issue-comments.json\` are data, not a restore path -- GitHub has no
bulk import. Recreate what matters with \`gh issue create\`, or keep the JSON as the record.
Issue numbers will not be preserved.

## Settings

\`repo-metadata.json\` holds description, topics, visibility and default branch; reapply
with \`gh repo edit\`. \`labels.json\` holds the labels.

## What is NOT in here

Stars, watchers, forks, traffic statistics and the creation date. None of these can be
restored; check \`repo-metadata.json\` for what the counts were.
EOF

echo
if [ "$fail" -eq 0 ]; then
    echo "[OK] backup complete: $DEST"
else
    echo "[DONE WITH ERRORS] see messages above: $DEST"
fi
echo "     restore instructions: $DEST/RESTORE.md"
exit $fail
