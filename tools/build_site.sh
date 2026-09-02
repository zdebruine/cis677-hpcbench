#!/usr/bin/env bash
# Build the full static leaderboard site into _site/.
#
# This is exactly what .github/workflows/publish.yml runs, so a green local run
# means a green deploy. Nothing here needs anything outside the standard
# library -- no build step, no bundler, no node.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-_site}"
rm -rf "$OUT"; mkdir -p "$OUT"

for t in tasks/*/task.yaml; do
  id=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['id'])" "$t")
  # HPC tier is authoritative and takes the plain path.
  python3 -m hpcbench.leaderboard --task "$t" --results results --tier hpc  --out "$OUT/$id.html"
  python3 -m hpcbench.leaderboard --task "$t" --results results --tier cloud --out "$OUT/$id-cloud.html"
done

python3 -m hpcbench.index --tasks tasks --out "$OUT/index.html"
cp "$OUT/index.html" "$OUT/404.html"

# Pages serves the uploaded artifact as-is, but .nojekyll costs nothing and
# keeps things working if the site is ever served from a branch instead.
touch "$OUT/.nojekyll"

echo
echo "built $OUT/  ($(find "$OUT" -name '*.html' | wc -l) pages)"
echo "preview:  python3 -m http.server -d $OUT 8000"
