#!/bin/bash
# Run every submission for one task on an exclusive node, and write a device
# bundle. Usage:  sbatch clipper/run_all.sbatch p1-kernel
#
#SBATCH --job-name=hpcbench-device
#SBATCH --partition=class
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --exclusive
#SBATCH --constraint=cis677score
#SBATCH --output=hpcbench-device-%j.out
set -euo pipefail

TASK="${1:-p1-kernel}"
ROOT="${HPCBENCH_ROOT:-$SLURM_SUBMIT_DIR}"
cd "$ROOT"

module load gcc cmake python 2>/dev/null || true

# The corpus is rebuilt rather than shipped: 296 MB has no business in git, and
# regenerating it from the packed matrix is deterministic.
if [ ! -f "data/$TASK/public.bin" ]; then
  python3 tools/make_p1_input.py --variant public --out "data/$TASK/public.bin"
fi

python3 -m hpcbench.device \
    --task "tasks/$TASK/task.yaml" \
    --submissions submissions \
    --baseline "baselines/$TASK" \
    --input-path "data/$TASK/public.bin" \
    --device-kind hpc \
    --device-label "Clipper ${SLURM_JOB_PARTITION:-class} / $(scontrol show hostnames "$SLURM_JOB_NODELIST" 2>/dev/null | head -1)" \
    --out results/devices

echo "Done. Commit results/devices and push, or send the JSON to the instructor."
