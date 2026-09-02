#!/usr/bin/env bash
# One submission, scored under identical conditions for everyone.
#
# --constraint is THE fairness requirement. The class partition spans 48-, 40-,
# 52- and 64-core hosts; without pinning, the leaderboard ranks luck. Ask ARC
# for a feature tag and set HPCBENCH_CONSTRAINT to it.
#SBATCH --partition=class
#SBATCH --account=cis677
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:45:00
#SBATCH --constraint=cis677score
#SBATCH --exclusive
set -euo pipefail

module load gcc/13.2.0 cmake python/3.11 2>/dev/null || true

export HPCBENCH_TIER=hpc
export OMP_NUM_THREADS=4
export OMP_PROC_BIND=close
export OMP_PLACES=cores

OUT="$WORK/results/${TASK_ID}/${HANDLE}-${WHICH}-${SHA}.json"
mkdir -p "$(dirname "$OUT")"

echo "node=$(hostname)  job=${SLURM_JOB_ID}  handle=${HANDLE}  commit=${SHA}"

# Everything runs inside the pinned image so the toolchain is identical for
# every submission and reproducible next semester.
apptainer exec --cleanenv \
  --env HPCBENCH_TIER=hpc,OMP_NUM_THREADS=4,OMP_PROC_BIND=close,OMP_PLACES=cores \
  --bind "$WORK:$WORK,$ROOT:$ROOT" \
  "$ROOT/hpcbench.sif" \
  python3 -m hpcbench.run \
    --task "$ROOT/tasks/${TASK_ID}/task.yaml" \
    --submission "$DEST" \
    --input-path "$ROOT/data/${TASK_ID}/${WHICH}.bin" \
    --input "$WHICH" \
    --tier hpc \
    --handle "$HANDLE" \
    --out "$OUT" \
  > /dev/null || echo "  (evaluation reported a failure; the record explains why)"

# Resource accounting, for the efficiency metric and for teaching queue citizenship.
sleep 20
jobstats "${SLURM_JOB_ID}" 2>/dev/null | tee "$WORK/logs/${SLURM_JOB_ID}.jobstats" || true
