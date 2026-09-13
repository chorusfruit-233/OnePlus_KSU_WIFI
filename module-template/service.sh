#!/system/bin/sh
MODDIR=${0%/*}; LOG=/data/adb/oneplus-wifi-lkm.log; KSUD=/data/adb/ksud
[ -x "$KSUD" ] || { echo "wifi-lkm: ksud not found" >> "$LOG"; exit 0; }
EXPECTED=$(cat "$MODDIR/kernel.release" 2>/dev/null || true); CURRENT=$(uname -r)
[ -n "$EXPECTED" ] && [ "$CURRENT" = "$EXPECTED" ] || { echo "wifi-lkm: kernel mismatch $CURRENT != $EXPECTED" >> "$LOG"; exit 1; }
# modules.load is generated from modinfo dependencies (dependencies precede consumers).
if [ -r "$MODDIR/modules.load" ]; then
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    [ -f "$MODDIR/$rel" ] || { echo "wifi-lkm: missing $rel" >> "$LOG"; exit 1; }
    "$KSUD" insmod "$MODDIR/$rel" >> "$LOG" 2>&1 || { echo "wifi-lkm: failed $rel" >> "$LOG"; exit 1; }
  done < "$MODDIR/modules.load"
else
  echo "wifi-lkm: modules.load missing" >> "$LOG"; exit 1
fi
