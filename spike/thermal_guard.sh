#!/usr/bin/env bash
# Pause (SIGSTOP) our benchmark python processes while any thermal zone is >= 95 C; resume below 85 C.
LOG="$(dirname "$0")/results/telemetry.log"; paused=0
while true; do
  t=$(( $(sort -n /sys/class/thermal/thermal_zone*/temp | tail -1) / 1000 ))
  pids=$(pgrep -f "spike/(asr_bench|longform_bench|diar_bench|vllm_bench)\.py")
  if [ $paused = 0 ] && [ $t -ge 95 ] && [ -n "$pids" ]; then kill -STOP $pids; paused=1; echo "$(date +%T) GUARD pause at ${t}C" >> "$LOG"; sync "$LOG"
  elif [ $paused = 1 ] && [ $t -le 85 ]; then kill -CONT $pids 2>/dev/null; paused=0; echo "$(date +%T) GUARD resume at ${t}C" >> "$LOG"; sync "$LOG"; fi
  sleep 1
done
