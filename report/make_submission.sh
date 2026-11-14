#!/usr/bin/env bash
# Build the CO4031 submission ZIP: report.pdf, slides.pdf, src/, data/.
# Usage: report/make_submission.sh            (run from anywhere inside the repo)
# Output: report/dist/CO4031_Nhom7_L02.zip
set -euo pipefail

repo=$(git rev-parse --show-toplevel)
cd "$repo/report"

name=CO4031_Nhom7_L02
out=dist/$name
rm -rf dist
mkdir -p "$out/src" "$out/data"

# 1. Report and slides (rebuild when tectonic is installed).
if command -v tectonic >/dev/null; then
  tectonic report.tex >/dev/null 2>&1
  tectonic slides.tex >/dev/null 2>&1
fi
cp report.pdf slides.pdf "$out/"

# 2. Source code at the current commit. data/ is shipped separately below.
git -C "$repo" archive --format=tar HEAD -- . ':!data' ':!report/dist' | tar -x -C "$out/src"

# 3. Sample data: raw Binance archives for BTC, ETH, SOL, September 2026.
#    Taken from the local cache data/raw/binance; downloads them if missing.
base=https://data.binance.vision/data/spot
for sym in BTCUSDT ETHUSDT SOLUSDT; do
  for iv in 1d 1h; do
    f=$sym-$iv-2026-09.zip
    dst=$out/data/binance/$sym/$iv
    mkdir -p "$dst"
    if [ -f "$repo/data/raw/binance/$sym/$iv/$f" ]; then
      cp "$repo/data/raw/binance/$sym/$iv/$f" "$dst/"
    else
      curl -sfL -o "$dst/$f" "$base/monthly/klines/$sym/$iv/$f"
    fi
  done
done
cat > "$out/data/README.md" <<'EOF'
# Dữ liệu mẫu

Nến 1d và 1h của BTC, ETH, SOL tháng 9/2026, đúng định dạng archive gốc mà ETL đọc
(Binance Public Data, https://data.binance.vision). Toàn bộ dữ liệu tải lại được bằng
`make extract-daily` hoặc `pipeline/batch/ingest_binance_history.py` (xem src/README.md).
EOF

cat > "$out/README.txt" <<'EOF'
CO4031 - Nhom 7 - Lop L02 - CoinSight

report.pdf   Bao cao (link video o trang bia)
slides.pdf   Slide thuyet trinh
src/         Ma nguon; ban moi nhat: https://github.com/caoTayTang/CoinSight
data/        Du lieu mau
EOF

(cd dist && zip -qr "$name.zip" "$name")
rm -rf "$out"
ls -lh "dist/$name.zip"
