#!/bin/bash
# =============================================================================
# run-tasks.sh — 无人值守跑 docs/TASKS.md 的任务序列
#
# 每个任务两个全新的无头会话（等效手动开新会话，无上下文漂移）：
#   1) Doer     执行任务并 commit（读到上一轮 blockers 会优先修复）
#   2) Verifier 独立验收：亲手重跑验收命令，写 .runner/verdicts/<task>.json
# 验收 pass → 下一个任务；fail → blockers 回灌给 Doer 重试（每任务最多 3 轮）
# 撞到重试上限或 Doer 主动升级（.runner/escalation/）→ 停下等人
#
# 用法:
#   ./scripts/run-tasks.sh T01 T06        # 从 T01 干到 T06 后停（检查点）
#   ./scripts/run-tasks.sh T07 T15        # 第二段
#   DOER_MODEL=MiniMax-M2.7 VERIFIER_MODEL=claude-haiku-4-5-20251001 \
#     ./scripts/run-tasks.sh T01 T06
# =============================================================================
set -u

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly PROMPTS_DIR="$SCRIPT_DIR/prompts"
readonly RUNNER_DIR="$REPO_DIR/.runner"
readonly LOG_DIR="$RUNNER_DIR/logs"

# 模型分档：Doer 用便宜档，Verifier 默认另一个便宜档（独立性 + 防同模型盲区）
DOER_MODEL="${DOER_MODEL:-${AUTODEV_MODEL:-MiniMax-M2.7}}"
VERIFIER_MODEL="${VERIFIER_MODEL:-claude-haiku-4-5-20251001}"
MAX_ROUNDS_PER_TASK="${MAX_ROUNDS_PER_TASK:-3}"
SESSION_TIMEOUT="${SESSION_TIMEOUT:-3600}"  # 单会话最长 1h

FROM_TASK="${1:?用法: run-tasks.sh <FROM> <TO>，例如 run-tasks.sh T01 T06}"
TO_TASK="${2:?用法: run-tasks.sh <FROM> <TO>，例如 run-tasks.sh T01 T06}"

# Preflight：jq 缺了就早失败。少了它 verdict_passed() 会把 valid JSON 误判为 invalid，
# 然后每任务默默跑满 3 轮再撞上限，浪费 doer/verifier token。
command -v jq >/dev/null 2>&1 || {
    echo "❌ 缺少 jq（解析 .runner/verdicts/*.json 用）。" >&2
    echo "   安装:  apt-get install jq   # Debian/Ubuntu" >&2
    echo "          brew install jq      # macOS" >&2
    exit 1
}

mkdir -p "$RUNNER_DIR/verdicts" "$RUNNER_DIR/feedback" "$RUNNER_DIR/escalation" "$LOG_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_DIR/runner.log"; }

# 从 docs/TASKS.md 抽取 FROM..TO 的任务编号序列（按文档出现顺序）
task_list() {
    grep -oE '^### (T[0-9]{2})' "$REPO_DIR/docs/TASKS.md" | awk '{print $2}' \
        | awk -v from="$FROM_TASK" -v to="$TO_TASK" '
            $0 == from {on=1} on {print} $0 == to {exit}'
}

# 起一个全新无头会话（新进程 = 天然全新 context，等效 /clear）
run_session() {
    local role="$1" task_id="$2" round="$3"
    local prompt_file="$PROMPTS_DIR/$role.md"
    local model log_file
    case "$role" in
        doer)     model="$DOER_MODEL" ;;
        verifier) model="$VERIFIER_MODEL" ;;
    esac
    log_file="$LOG_DIR/${task_id}-round${round}-${role}.log"

    # 权限走仓库 .claude/settings.local.json 白名单（不用 dangerously-skip-permissions，
    # 见 ~/.claude/rules/common/hooks.md）。acceptEdits 只自动化文件编辑，Bash 仍受白名单约束。
    log "  ▶ $role 会话启动 (model=$model) → $log_file"
    sed "s/{{TASK_ID}}/$task_id/g" "$prompt_file" \
        | (cd "$REPO_DIR" && timeout "$SESSION_TIMEOUT" \
             claude -p --model "$model" --permission-mode acceptEdits) \
        > "$log_file" 2>&1
    local code=$?
    log "  ◀ $role 会话结束 (exit=$code)"
    return $code
}

# 校验 verdict：文件存在、合法 JSON、pass==true、commands_run 非空
verdict_passed() {
    local verdict="$RUNNER_DIR/verdicts/$1.json"
    [[ -f "$verdict" ]] || { log "  ✗ verdict 文件缺失"; return 1; }
    jq -e '.pass == true and (.commands_run | length > 0)' "$verdict" >/dev/null 2>&1
}

run_task() {
    local task_id="$1" round=1
    rm -f "$RUNNER_DIR/feedback/$task_id.json"

    while (( round <= MAX_ROUNDS_PER_TASK )); do
        log "━━━ $task_id round $round/$MAX_ROUNDS_PER_TASK ━━━"

        run_session doer "$task_id" "$round" || log "  ⚠ doer 非零退出，仍交给验收判定"

        if [[ -f "$RUNNER_DIR/escalation/$task_id.md" ]]; then
            log "  🛑 Doer 主动升级：.runner/escalation/$task_id.md"
            return 2
        fi

        run_session verifier "$task_id" "$round" || log "  ⚠ verifier 非零退出"

        if verdict_passed "$task_id"; then
            log "  ✅ $task_id 验收通过"
            return 0
        fi

        # 失败：把 blockers 回灌给下一轮 Doer（Doer 看不到 verifier transcript，只看 verdict）
        if [[ -f "$RUNNER_DIR/verdicts/$task_id.json" ]]; then
            cp "$RUNNER_DIR/verdicts/$task_id.json" "$RUNNER_DIR/feedback/$task_id.json"
            log "  ↺ 验收未过，blockers 已回灌: $(jq -c '.blockers' "$RUNNER_DIR/feedback/$task_id.json" 2>/dev/null | head -c 300)"
        else
            echo "{\"task\":\"$task_id\",\"pass\":false,\"blockers\":[\"verifier 未产出 verdict，检查 $LOG_DIR/${task_id}-round${round}-verifier.log\"],\"commands_run\":[]}" \
                > "$RUNNER_DIR/feedback/$task_id.json"
        fi
        (( round++ ))
    done

    log "  🛑 $task_id 撞到 $MAX_ROUNDS_PER_TASK 轮上限，停下等人仲裁"
    return 1
}

# === Main ===
TASKS="$(task_list)"
[[ -n "$TASKS" ]] || { log "❌ 在 docs/TASKS.md 中找不到 $FROM_TASK..$TO_TASK"; exit 1; }

log "═══ run-tasks 启动: $(echo $TASKS | tr '\n' ' ') ═══"
log "    Doer=$DOER_MODEL  Verifier=$VERIFIER_MODEL  每任务最多 $MAX_ROUNDS_PER_TASK 轮"

for task_id in $TASKS; do
    # 已验收通过的任务跳过（断点续跑）
    if verdict_passed "$task_id"; then
        log "⏭  $task_id 已有通过的 verdict，跳过"
        continue
    fi
    run_task "$task_id"
    rc=$?
    if (( rc != 0 )); then
        log "═══ 在 $task_id 停止 (rc=$rc)。查看: .runner/verdicts/ .runner/escalation/ $LOG_DIR ═══"
        exit $rc
    fi
done

log "═══ 全部完成: $FROM_TASK → $TO_TASK。到检查点了，请人工/架构档 review ═══"
