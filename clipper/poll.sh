#!/usr/bin/env bash
# ============================================================================
# hpcbench pull-model scorer for GVSU Clipper.
#
# Runs as a cron job under the COURSE account on the login node. It reaches
# OUT to GitHub over HTTPS -- nothing ever connects in. There is no daemon,
# no self-hosted runner, no long-lived credential with cluster access sitting
# in GitHub, and no MFA problem. This is the architecture ARC will approve.
#
#   crontab -e
#   0 2 * * *  /mnt/projects/cis677/hpcbench/clipper/poll.sh >> ~/hpcbench.log 2>&1
#
# Requires in the environment (put them in ~/.hpcbench.env, chmod 600):
#   GITHUB_TOKEN   fine-grained PAT, read on student repos + write on grader repo
#   GRADER_REPO    e.g. gvsu-cis677/grader
#   ROSTER         path to roster.tsv:  handle <TAB> repo_url
# ============================================================================
set -euo pipefail

ROOT="${HPCBENCH_ROOT:-/mnt/projects/cis677/hpcbench}"
WORK="${HPCBENCH_WORK:-/mnt/projects/cis677/scoring}"
source "${HOME}/.hpcbench.env"

TASK_ID="${1:-}"
if [[ -z "$TASK_ID" ]]; then
  echo "usage: poll.sh <task-id> [public|holdout]" >&2; exit 2
fi
WHICH="${2:-public}"

mkdir -p "$WORK/repos" "$WORK/results" "$WORK/logs"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "=== hpcbench poll  task=$TASK_ID  input=$WHICH  $STAMP"

# ---- 1. refresh the grader repo (tasks, reference digests, scorer) ---------
if [[ -d "$ROOT/.git" ]]; then
  git -C "$ROOT" fetch --quiet origin && git -C "$ROOT" reset --hard --quiet origin/main
else
  git clone --quiet "https://x-access-token:${GITHUB_TOKEN}@github.com/${GRADER_REPO}.git" "$ROOT"
fi

# ---- 2. clone or update every student repo --------------------------------
while IFS=$'\t' read -r HANDLE REPO_URL; do
  [[ -z "${HANDLE:-}" || "$HANDLE" == \#* ]] && continue
  DEST="$WORK/repos/$HANDLE"
  AUTHED="${REPO_URL/https:\/\//https://x-access-token:${GITHUB_TOKEN}@}"
  if [[ -d "$DEST/.git" ]]; then
    git -C "$DEST" fetch --quiet origin && git -C "$DEST" reset --hard --quiet origin/HEAD || {
      echo "  !! $HANDLE: fetch failed, skipping"; continue; }
  else
    git clone --quiet "$AUTHED" "$DEST" || { echo "  !! $HANDLE: clone failed"; continue; }
  fi
  SHA=$(git -C "$DEST" rev-parse --short HEAD)

  # Skip work we have already done for this exact commit.
  MARK="$WORK/results/${TASK_ID}/${HANDLE}-${WHICH}-${SHA}.json"
  if [[ -f "$MARK" ]]; then echo "  == $HANDLE @$SHA already scored"; continue; fi

  echo "  -> queueing $HANDLE @$SHA"
  sbatch --parsable \
    --job-name="score-${TASK_ID}-${HANDLE}" \
    --output="$WORK/logs/%j.out" \
    --export=ALL,HANDLE="$HANDLE",TASK_ID="$TASK_ID",WHICH="$WHICH",DEST="$DEST",ROOT="$ROOT",WORK="$WORK",SHA="$SHA" \
    "$ROOT/clipper/score.sbatch"
done < "$ROSTER"

echo "=== all jobs queued. Results are committed by collect.sh once they land."
