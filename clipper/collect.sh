#!/usr/bin/env bash
# Push finished result records back to the grader repo. GitHub Pages rebuilds
# from the push. Outbound HTTPS only.
set -euo pipefail
ROOT="${HPCBENCH_ROOT:-/mnt/projects/cis677/hpcbench}"
WORK="${HPCBENCH_WORK:-/mnt/projects/cis677/scoring}"
source "${HOME}/.hpcbench.env"

cd "$ROOT"
git fetch --quiet origin && git reset --hard --quiet origin/main
mkdir -p results
rsync -a "$WORK/results/" results/

if git diff --quiet -- results; then
  echo "no new results"; exit 0
fi
N=$(git status --porcelain -- results | wc -l)
git add results
git -c user.name="hpcbench" -c user.email="noreply@gvsu.edu" \
    commit -qm "results: $N record(s) from $(date -u +%FT%TZ)"
git push --quiet "https://x-access-token:${GITHUB_TOKEN}@github.com/${GRADER_REPO}.git" HEAD:main
echo "pushed $N result record(s)"
