#!/usr/bin/env bash
# Append GPU/CPU/mem readings every 2 s, synced to disk, to diagnose hard resets.
LOG="$(dirname "$0")/results/telemetry.log"
while true; do
  g=$(nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.gr,utilization.gpu --format=csv,noheader,nounits 2>/dev/null)
  t=$(sort -n /sys/class/thermal/thermal_zone*/temp 2>/dev/null | tail -1)
  m=$(free -m | awk 'NR==2{print $3}')
  echo "$(date +%T) gpu[temp,W,MHz,util]=$g maxzone=$((t/1000))C memMiB=$m load=$(cut -d' ' -f1 /proc/loadavg)" >> "$LOG"
  sync "$LOG"; sleep 2
done
