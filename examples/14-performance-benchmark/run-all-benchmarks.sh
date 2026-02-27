#!/usr/bin/env bash
# ==============================================================================
# 全ベンチマーク統合実行スクリプト
#
# すべてのベンチマークを順次実行し、結果を BENCHMARK_RESULTS.md に統合する。
# グラフ用の CSV ファイルも生成する。
#
# Usage:
#   ./run-all-benchmarks.sh
#   ./run-all-benchmarks.sh --dry-run
#   ./run-all-benchmarks.sh --iterations 500
#   ./run-all-benchmarks.sh --output-dir ./results
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="${SCRIPT_DIR}/results-${TIMESTAMP}"
ITERATIONS=1000
DRY_RUN=""
PYTHON="${PYTHON:-python3}"

# コマンドライン引数のパース
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --iterations)
            ITERATIONS="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run           ダミーデータで実行（API 呼び出しなし）"
            echo "  --iterations N      測定回数（デフォルト: 1000）"
            echo "  --output-dir DIR    結果の出力先ディレクトリ"
            echo "  --help              このヘルプメッセージを表示"
            exit 0
            ;;
        *)
            echo "[ERROR] 不明なオプション: $1"
            exit 1
            ;;
    esac
done

echo "============================================================"
echo "Performance Benchmark Suite"
echo "============================================================"
echo "  タイムスタンプ: ${TIMESTAMP}"
echo "  出力ディレクトリ: ${OUTPUT_DIR}"
echo "  測定回数: ${ITERATIONS}"
echo "  Dry-run: ${DRY_RUN:-disabled}"
echo "============================================================"

mkdir -p "${OUTPUT_DIR}"

# 各ベンチマークの実行状態を追跡
BENCHMARKS_RUN=0
BENCHMARKS_FAILED=0

run_benchmark() {
    local name="$1"
    local script="$2"
    local output_file="${OUTPUT_DIR}/${name}.json"

    echo ""
    echo "------------------------------------------------------------"
    echo "[START] ${name}"
    echo "------------------------------------------------------------"

    if "${PYTHON}" "${SCRIPT_DIR}/${script}" \
        --iterations "${ITERATIONS}" \
        ${DRY_RUN} \
        --output "${output_file}"; then
        echo "[OK] ${name} が完了しました -> ${output_file}"
        BENCHMARKS_RUN=$((BENCHMARKS_RUN + 1))
    else
        echo "[NG] ${name} が失敗しました"
        BENCHMARKS_FAILED=$((BENCHMARKS_FAILED + 1))
    fi
}

# --- ベンチマーク実行 ---
run_benchmark "cedar-latency" "benchmark-cedar-latency.py"
run_benchmark "dynamodb-throughput" "benchmark-dynamodb-throughput.py"
run_benchmark "memory-api" "benchmark-memory-api.py"
run_benchmark "interceptor-lambda" "benchmark-interceptor-lambda.py"

# --- CSV ファイル生成 ---
echo ""
echo "------------------------------------------------------------"
echo "[START] CSV ファイル生成"
echo "------------------------------------------------------------"

CSV_FILE="${OUTPUT_DIR}/benchmark-summary.csv"
echo "benchmark,scenario,count,mean_ms,median_ms,p95_ms,p99_ms,min_ms,max_ms,stdev_ms,errors" > "${CSV_FILE}"

for json_file in "${OUTPUT_DIR}"/*.json; do
    if [[ ! -f "${json_file}" ]]; then
        continue
    fi

    benchmark_name="$(${PYTHON} -c "
import json, sys
with open('${json_file}') as f:
    data = json.load(f)
print(data.get('benchmark', 'unknown'))
" 2>/dev/null || echo "unknown")"

    ${PYTHON} -c "
import json, sys
with open('${json_file}') as f:
    data = json.load(f)
for scenario_name, scenario_data in data.get('scenarios', {}).items():
    stats = scenario_data.get('stats', {})
    errors = scenario_data.get('errors', 0)
    print(','.join([
        '${benchmark_name}',
        scenario_name,
        str(stats.get('count', 0)),
        str(stats.get('mean', 0)),
        str(stats.get('median', 0)),
        str(stats.get('p95', 0)),
        str(stats.get('p99', 0)),
        str(stats.get('min', 0)),
        str(stats.get('max', 0)),
        str(stats.get('stdev', 0)),
        str(errors),
    ]))
" 2>/dev/null >> "${CSV_FILE}" || true
done

echo "[OK] CSV ファイルを生成しました: ${CSV_FILE}"

# --- BENCHMARK_RESULTS.md 生成 ---
echo ""
echo "------------------------------------------------------------"
echo "[START] BENCHMARK_RESULTS.md 生成"
echo "------------------------------------------------------------"

RESULTS_MD="${OUTPUT_DIR}/BENCHMARK_RESULTS.md"

${PYTHON} -c "
import json
import glob
import os

output_dir = '${OUTPUT_DIR}'
timestamp = '${TIMESTAMP}'

lines = []
lines.append('# Performance Benchmark Results')
lines.append('')
lines.append(f'実行日時: {timestamp}')
lines.append(f'測定回数: ${ITERATIONS}')
lines.append('')

json_files = sorted(glob.glob(os.path.join(output_dir, '*.json')))

for json_file in json_files:
    with open(json_file) as f:
        data = json.load(f)

    benchmark_name = data.get('benchmark', os.path.basename(json_file))
    lines.append(f'## {benchmark_name}')
    lines.append('')

    lines.append('| Scenario | Count | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) | Errors |')
    lines.append('|----------|-------|-----------|-------------|----------|----------|----------|----------|--------|')

    for scenario_name, scenario_data in data.get('scenarios', {}).items():
        stats = scenario_data.get('stats', {})
        errors = scenario_data.get('errors', 0)
        lines.append(
            f'| {scenario_name} '
            f'| {stats.get(\"count\", 0)} '
            f'| {stats.get(\"mean\", 0)} '
            f'| {stats.get(\"median\", 0)} '
            f'| {stats.get(\"p95\", 0)} '
            f'| {stats.get(\"p99\", 0)} '
            f'| {stats.get(\"min\", 0)} '
            f'| {stats.get(\"max\", 0)} '
            f'| {errors} |'
        )
    lines.append('')

lines.append('---')
lines.append('')
lines.append('Generated by run-all-benchmarks.sh')

with open('${RESULTS_MD}', 'w') as f:
    f.write('\n'.join(lines))

print('[OK] BENCHMARK_RESULTS.md を生成しました')
" 2>/dev/null || echo "[WARNING] BENCHMARK_RESULTS.md の生成に失敗しました"

# --- サマリー ---
echo ""
echo "============================================================"
echo "Benchmark Suite Summary"
echo "============================================================"
echo "  実行成功: ${BENCHMARKS_RUN}"
echo "  実行失敗: ${BENCHMARKS_FAILED}"
echo "  出力ディレクトリ: ${OUTPUT_DIR}"
echo ""
echo "  生成ファイル:"
ls -la "${OUTPUT_DIR}/" 2>/dev/null | tail -n +4
echo "============================================================"

if [[ ${BENCHMARKS_FAILED} -gt 0 ]]; then
    echo "[WARNING] ${BENCHMARKS_FAILED} 件のベンチマークが失敗しました"
    exit 1
fi

echo "[OK] すべてのベンチマークが正常に完了しました"
