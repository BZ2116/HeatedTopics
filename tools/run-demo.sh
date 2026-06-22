#!/bin/bash
# 一键运行 heatedTopics Demo
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$PROJECT_DIR/tools"
DAILYHOT_DIR="$TOOLS_DIR/DailyHotApi"
API_PORT=6688

echo "=== 1. 启动 DailyHotApi ==="
# Kill any existing process on port
lsof -ti :$API_PORT | xargs kill -9 2>/dev/null || true

cd "$DAILYHOT_DIR"
PORT=$API_PORT npm run dev > /dev/null 2>&1 &
API_PID=$!
echo "DailyHotApi PID: $API_PID"

# Wait for API to be ready
echo -n "等待 API 启动"
for i in $(seq 1 20); do
    if curl -s "http://localhost:$API_PORT/weibo" > /dev/null 2>&1; then
        echo ""
        echo "API 就绪"
        break
    fi
    if [ $i -eq 20 ]; then
        echo "API 启动超时"
        kill $API_PID 2>/dev/null || true
        exit 1
    fi
    echo -n "."
    sleep 0.5
done

echo ""
echo "=== 2. 运行 Demo Pipeline ==="
cd "$PROJECT_DIR"
DAILY_HOT_API_BASE="http://localhost:$API_PORT" \
PYTHONPATH="$PROJECT_DIR" \
python3 -m src.demo_collect_hot_topics

echo ""
echo "=== 3. 生成的报告 ==="
echo "- 简报: $PROJECT_DIR/reports/daily_digest_demo.md"
echo "- 话题卡: $PROJECT_DIR/reports/hot_topic_cards.md"
echo "- HTML: $PROJECT_DIR/reports/daily_digest_demo.html"
echo "- 热榜数据: $PROJECT_DIR/data/hot_list.json"
echo "- 精选话题: $PROJECT_DIR/data/selected_topics.json"

kill $API_PID 2>/dev/null || true
echo ""
echo "Demo 完成，API 已关闭"