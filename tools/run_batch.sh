#!/bin/bash
# 批次監督:批次退出(正常完成或死亡)後自動重啟續跑,
# 直到所有值處理完(progress 達到 TOTAL)為止。
TOTAL=38621
cd "$(dirname "$0")/.."
while true; do
    pgrep -f "python3 -B tools/taiwanize_sent" >/dev/null && sleep 10 && continue
    N=$(python3 -B -c "import json; print(len(json.load(open('tools/.taiwan_sent_progress.json', encoding='utf-8'))))")
    echo "[$(date +%F_%T)] 監督:進度 $N/$TOTAL" >> tools/taiwan_batch.log
    if [ "$N" -ge "$TOTAL" ]; then
        echo "[$(date +%F_%T)] 全部完成 ✓" >> tools/taiwan_batch.log
        exit 0
    fi
    python3 -B tools/taiwanize_sent.py >> tools/taiwan_batch.log 2>&1
    sleep 3
done