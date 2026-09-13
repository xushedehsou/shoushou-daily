#!/bin/bash
# Generates daily reports, catching up on any past day that has activity
# logs but no report yet. This matters because launchd's StartCalendarInterval
# job can fire late (e.g. the laptop was asleep at 21:00 and only wakes up
# the next day) — using "today" as the target date would then generate a
# report for the wrong day. Instead we scan raw/ for missing reports.

set -euo pipefail

# launchd does not inherit the interactive shell PATH. Keep Node available so
# the Codex CLI's /usr/bin/env node entrypoint can start from the scheduled job.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

ROOT="$HOME/shoushou-daily"
if [ -n "$(printenv SHOUSHOU_ROOT 2>/dev/null)" ]; then ROOT="$(printenv SHOUSHOU_ROOT)"; fi
OBSIDIAN_DIR="$ROOT/reports"
if [ -n "$(printenv SHOUSHOU_OBSIDIAN_DIR 2>/dev/null)" ]; then OBSIDIAN_DIR="$(printenv SHOUSHOU_OBSIDIAN_DIR)"; fi
CODEX_BIN="$(printenv SHOUSHOU_CODEX_BIN 2>/dev/null || command -v codex || true)"
CODEX_MODEL="$(printenv SHOUSHOU_CODEX_MODEL 2>/dev/null || true)"
[ -n "$CODEX_MODEL" ] || CODEX_MODEL="gpt-5.6-luna"
CODEX_REASONING="$(printenv SHOUSHOU_CODEX_REASONING 2>/dev/null || true)"
[ -n "$CODEX_REASONING" ] || CODEX_REASONING="low"
PYTHON_BIN="$(printenv SHOUSHOU_PYTHON_BIN 2>/dev/null || command -v python3 || true)"
TODAY="$(date +%Y-%m-%d)"

[ -n "$PYTHON_BIN" ] || { echo "python3 is required" >&2; exit 1; }
mkdir -p "$OBSIDIAN_DIR"

run_for_day() {
    local day="$1"
    local log_file="$ROOT/raw/$day/activity.jsonl"
    local report_file="$OBSIDIAN_DIR/$day.md"

    [ -s "$log_file" ] || return 0
    [ -f "$report_file" ] && [ "${REBUILD_REPORTS:-0}" != "1" ] && return 0

    local reminders_file="$ROOT/raw/$day/reminders.json"
    "$PYTHON_BIN" "$ROOT/scripts/reminders_snapshot.py" "$day" > "$reminders_file" 2>>"$ROOT/logs/report.log" || true
    local ticktick_file="$ROOT/raw/$day/ticktick.json"
    if [ -f "$ROOT/scripts/ticktick_snapshot.py" ]; then
        "$PYTHON_BIN" "$ROOT/scripts/ticktick_snapshot.py" "$day" > "$ticktick_file" 2>>"$ROOT/logs/report.log" || true
    fi
    local ai_activity_file="$ROOT/raw/$day/ai_activity.json"
    "$PYTHON_BIN" "$ROOT/scripts/collect_ai_activity.py" "$day" > "$ai_activity_file" 2>>"$ROOT/logs/report.log" || true
    local screenshot_evidence_file="$ROOT/raw/$day/screenshot_evidence.json"
    "$PYTHON_BIN" "$ROOT/scripts/collect_screenshot_evidence.py" "$day" > /dev/null 2>>"$ROOT/logs/report.log" || true
    local activity_timeline_file="$ROOT/raw/$day/activity_timeline.json"
    "$PYTHON_BIN" "$ROOT/scripts/build_activity_timeline.py" "$day" --output "$activity_timeline_file" >> "$ROOT/logs/report.log" 2>&1 || true
    local image_args=()
    while IFS= read -r image_path; do
        [ -n "$image_path" ] && image_args+=(--image "$image_path")
    done < <("$PYTHON_BIN" "$ROOT/scripts/collect_screenshot_evidence.py" "$day" --paths-only 2>>"$ROOT/logs/report.log")

    # Keep the prompt structured and scannable. The headings are deliberately
    # short English labels so the HTML reading surface stays compact.
    prompt=$(cat <<EOF
这是已授权的定时自动化任务。不要提问、不要等待用户确认、不要只返回计划或要求用户回复“执行”；请立即读取数据、生成内容并写入目标文件。完成后只需返回一行简短状态。

读取 ${activity_timeline_file}、${ROOT}/raw/${day}/activity.jsonl、${ai_activity_file}、${screenshot_evidence_file}、${reminders_file} 和 ${ticktick_file}（缺失或读取失败就跳过）。本次任务已经把当天均匀抽取的截图作为图像附件传入；必须先看这些截图，再结合结构化活动记录、会话和窗口记录判断实际工作。会话、截图、绘画记录和 TickTick 都只是原始材料，不能原文抄写，必须先加工成客观、明确、正式的工作描述，再写入 ${report_file}。

日报是极简的个人日志，不写“今天很忙”“最重要的推进”“三项关键决定”“不是……而是……”这类 AI 味总结。不要出现 AI Activity、Signals、Daily Log、Markdown、HTML、截图数量、会话数量等内部实现词。不要直接引用用户原话，不要保留口语、语气词和对话腔；把“想做什么”与“实际完成了什么”分开，把完成的工作和发生的生活动作写成明确描述。只写材料能支持的事实；没有证据就写“无”。当天有辨识度的浏览、阅读、聊天、购物、出行或其他生活动作也要记录，但不要把空闲、重复采样和单纯打开窗口写成行动。严格只输出以下二级标题，不要新增散文段落：

## Today
- 按项目概括当天实际完成的工程、研究、设计或整理工作，每个项目 1–4 条。先合并同一项目的多个会话，再把口语改成客观描述；不要写“某人说了什么”，要写“完成了什么工作、形成了什么结果”。绘画相关会话要写清楚人物、画面、提示词、风格或候选方案等实际产出。
- 不要把同一项目拆成多个伪项目。策略游戏相关的内容统一归入“某款策略游戏原型”，需要区分时在项目内部使用“玩法”“视觉美术”“工具与资料”等工作线；不要把“视觉套装”“资产评估”“人物界面玩法设计”单独当作项目。当天有明确的生活或浏览动作时，用“生活与浏览”归纳，不能虚构项目名。

## Timeline
- 按时间顺序列关键工作和生活节点，最多 12 条。每条必须保留可追溯信息，严格使用格式：「HH:MM–HH:MM｜应用：应用名｜项目：项目名或生活｜完成的工作、浏览或形成的产出｜时长：X 小时 Y 分钟｜来源：窗口活动记录 / 本地会话 / 截图识别 / TickTick」。应用名、时间段和来源必须来自结构化活动记录或截图；没有证据就不要编造。窗口标题只能证明看到过窗口，不能写成已经完成了里面的工作。截图识别出的联系人、消息摘要或网页内容要明确写“截图识别”；看不清就只写应用活动，不要猜。

## Projects
- 列出当天实际触碰的持续项目，以及当天发生的状态变化、产出或当前卡点；不要按会话数量罗列，不要把项目名本身当作进展；同一项目只列一次，并在其下合并玩法、视觉美术、工具与资料的变化；生活动作不要硬塞进项目；没有持续项目就写“无”。

## Ideas
- 只记录当天对话中明确出现、值得保留的想法；没有就写“无”。

## Questions
- 只记录当天留下的具体问题；没有就写“无”。

## Next
- 读取 TickTick 的当天新增事项、当天已完成事项和当前未完成事项。把口语化标题改写为正式、明确、可执行的任务；相关的新增或未完成事项列入 Next，已完成事项只在 Today 或 Projects 中作为已完成工作体现，不要把已完成事项再次列为下一步。生活事项也保留，但只改写为清楚的任务，不要凭空安排任务；没有就写“无”。

如果当天确实有新的工具、方法或事实发现，可以额外输出 ## Found；没有就不要创建这个标题。
在文档末尾单独写一行『活动时长（采样估算）：数字 小时』，例如『活动时长（采样估算）：9.5 小时』；数据不足时严格写『活动时长（采样估算）：数据不足，无法估算』。这只是窗口与会话采样覆盖的估算，不是精确工时。不要添加“约”“大约”“估算为”。
EOF
)

    cd "$ROOT"
    if ! perl -e 'alarm 180; exec @ARGV' "$CODEX_BIN" exec --ephemeral --skip-git-repo-check \
        --ignore-user-config --ignore-rules \
        --sandbox workspace-write --add-dir "$OBSIDIAN_DIR" \
        -m "$CODEX_MODEL" -c "model_reasoning_effort=\"$CODEX_REASONING\"" \
        "${image_args[@]}" \
        -- \
        "$prompt" \
        >> "$ROOT/logs/report.log" 2>&1; then
        echo "$(date): Codex analysis failed for $day; using local fallback" >> "$ROOT/logs/report.log"
    fi
    if [ ! -s "$report_file" ] || ! grep -q '^## Today$' "$report_file" || ! grep -Eq '^活动时长（采样估算）：([0-9]+([.][0-9]+)? 小时|数据不足，无法估算)$' "$report_file"; then
        "$PYTHON_BIN" "$ROOT/scripts/generate_fallback_report.py" "$day" "$report_file" >> "$ROOT/logs/report.log" 2>&1
    fi
    # Keep the parser contract stable when the model adds a harmless qualifier
    # such as "约" before an otherwise numeric estimate.
    if ! grep -Eq '^活动时长（采样估算）：([0-9]+([.][0-9]+)? 小时|数据不足，无法估算)$' "$report_file"; then
        sed -i '' -E 's/^活动时长（采样估算）：(约|大约|估算为)[[:space:]]*/活动时长（采样估算）：/' "$report_file"
    fi
    if ! grep -Eq '^活动时长（采样估算）：([0-9]+([.][0-9]+)? 小时|数据不足，无法估算)$' "$report_file"; then
        echo "$(date): invalid active-hours format in $report_file" >> "$ROOT/logs/report.log"
        return 1
    fi
    echo "$(date): generated report for $day" >> "$ROOT/logs/report.log"
}

# Only process days that are strictly in the past — "today" (per the
# calendar) is still in progress and shouldn't get a report yet. This job
# runs in the early hours of the next day, so "yesterday" is by then a
# complete, frozen day (recorder always writes to *today's* file, so a past
# day's activity.jsonl never gains new entries after midnight).
for day_dir in "$ROOT"/raw/*/; do
    day="$(basename "$day_dir")"
    if [ -n "${REPORT_DATES:-}" ]; then
        case ",${REPORT_DATES}," in
            *,${day},*) ;;
            *) continue ;;
        esac
    fi
    if [[ "$day" < "$TODAY" ]]; then
        run_for_day "$day"
    fi
done

# Refresh even when all reports already existed, so deleting or moving the
# HTML index never leaves the reading surface permanently stale.
"$PYTHON_BIN" "$ROOT/scripts/generate_dashboard.py" \
    --obsidian-dir "$OBSIDIAN_DIR" \
    --output "$OBSIDIAN_DIR/index.html" \
    >> "$ROOT/logs/report.log" 2>&1 || true
