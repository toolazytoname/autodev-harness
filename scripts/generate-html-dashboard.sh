#!/bin/bash
# generate-html-dashboard.sh - HTML Dashboard Generator
set -euo pipefail
HARNESS_DIR="./autodev-harness"
OUTPUT="${1:-./autodev-harness/dashboard.html}"

generate_html() {
  local task_data="null"
  local gan_data="null"
  local gate_status="{}"

  [ -f "${HARNESS_DIR}/state/task-queue.json" ] && \
    task_data=$(cat "${HARNESS_DIR}/state/task-queue.json")

  [ -f "${HARNESS_DIR}/feedback/gan/summary.json" ] && \
    gan_data=$(cat "${HARNESS_DIR}/feedback/gan/summary.json")

  for gate in lint build test e2e security; do
    local latest=$(ls -t "${HARNESS_DIR}/quality/gates/$gate/"*.log 2>/dev/null | head -1)
    if [ -n "$latest" ] && tail -1 "$latest" 2>/dev/null | grep -qE "PASS|passed|✓"; then
      gate_status=$(echo "$gate_status" | jq --arg g "$gate" --arg s "pass" '.[$g]=$s')
    else
      gate_status=$(echo "$gate_status" | jq --arg g "$gate" --arg s "fail" '.[$g]=$s')
    fi
  done

  cat > "$OUTPUT" << EOF
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AutoDevHarness Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 2rem; }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { color: #38bdf8; margin-bottom: 2rem; font-size: 1.8rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
  .card { background: #1e293b; border-radius: 12px; padding: 1.5rem; border: 1px solid #334155; }
  .card h2 { color: #94a3b8; font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 1rem; }
  .metric { font-size: 2.5rem; font-weight: 700; }
  .metric.green { color: #22c55e; }
  .metric.yellow { color: #eab308; }
  .metric.red { color: #ef4444; }
  .progress-bar { height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin: 1rem 0; }
  .progress-fill { height: 100%; background: linear-gradient(90deg, #22c55e, #84cc16); transition: width 0.3s; }
  .gates { display: flex; gap: 0.75rem; flex-wrap: wrap; }
  .gate { padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.875rem; }
  .gate.pass { background: #22c55e20; color: #22c55e; border: 1px solid #22c55e; }
  .gate.fail { background: #ef444420; color: #ef4444; border: 1px solid #ef4444; }
  .task-list { list-style: none; }
  .task-list li { padding: 0.5rem 0; border-bottom: 1px solid #334155; display: flex; align-items: center; gap: 0.75rem; }
  .task-list li:last-child { border-bottom: none; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; }
  .status-dot.completed { background: #22c55e; }
  .status-dot.in-progress { background: #eab308; }
  .status-dot.pending { background: #64748b; }
  .status-dot.failed { background: #ef4444; }
  .score-ring { width: 120px; height: 120px; border-radius: 50%; border: 8px solid #334155; display: flex; align-items: center; justify-content: center; font-size: 2rem; font-weight: 700; margin: 0 auto; }
  .score-ring.pass { border-color: #22c55e; color: #22c55e; }
  .score-ring.fail { border-color: #ef4444; color: #ef4444; }
  .timestamp { color: #64748b; font-size: 0.75rem; margin-top: 1rem; text-align: right; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  .live { animation: pulse 2s infinite; color: #22c55e; }
</style>
</head>
<body>
<div class="container">
  <h1>🤖 AutoDevHarness Dashboard <span class="live">● LIVE</span></h1>
  <div class="grid">
EOF

  # Task Progress Card
  local completed=$(echo "$task_data" | jq -r '.progress.completed // 0')
  local total=$(echo "$task_data" | jq -r '.tasks | length // 0')
  local pct=0
  [ "$total" -gt 0 ] && pct=$((completed * 100 / total))

  cat >> "$OUTPUT" << EOF
    <div class="card">
      <h2>Task Progress</h2>
      <div class="progress-bar"><div class="progress-fill" style="width: ${pct}%"></div></div>
      <div class="metric green">${completed}/${total}</div>
      <p style="color: #94a3b8; margin-top: 0.5rem">${pct}% complete</p>
      <ul class="task-list">
EOF

  [ -n "$task_data" ] && echo "$task_data" | jq -r '.tasks | sort_by(.priority) | .[0:5][] | "        <li><span class=\"status-dot \(.status)\"></span>\(.id): \(.name)</li>"' >> "$OUTPUT" 2>/dev/null

  cat >> "$OUTPUT" << EOF
      </ul>
    </div>
EOF

  # GAN Score Card
  local score=$(echo "$gan_data" | jq -r '.finalScore // 0' | cut -d. -f1)
  local passed=$(echo "$gan_data" | jq -r '.passed // false')
  local score_class="fail"
  [ "$passed" = "true" ] && score_class="pass"

  cat >> "$OUTPUT" << EOF
    <div class="card">
      <h2>GAN Quality Score</h2>
      <div class="score-ring $score_class">${score}</div>
      <p style="text-align: center; margin-top: 1rem; color: #94a3b8">
        $([ "$passed" = "true" ] && echo "✓ PASSED" || echo "⟳ In Progress")
      </p>
    </div>
EOF

  # Quality Gates Card
  cat >> "$OUTPUT" << EOF
    <div class="card">
      <h2>Quality Gates</h2>
      <div class="gates">
EOF

  for gate in lint build test e2e security; do
    local status=$(echo "$gate_status" | jq -r ".\"$gate\" // \"pending\"")
    [ "$status" = "pass" ] && echo "        <span class=\"gate pass\">✓ $gate</span>" >> "$OUTPUT"
    [ "$status" = "fail" ] && echo "        <span class=\"gate fail\">✗ $gate</span>" >> "$OUTPUT"
  done

  cat >> "$OUTPUT" << EOF
      </div>
    </div>
  </div>
  <p class="timestamp">Updated: $(date '+%Y-%m-%d %H:%M:%S')</p>
</div>
<script>
  // Auto-refresh every 30 seconds
  setTimeout(() => location.reload(), 30000);
</script>
</body>
</html>
EOF
  echo "Dashboard generated: $OUTPUT"
}

generate_html
