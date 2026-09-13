#!/system/bin/sh
MODDIR=${0%/*}; LOG=/data/adb/oneplus-wifi-lkm.log; KSUD=/data/adb/ksud
[ -x "$KSUD" ] || { echo "wifi-lkm: ksud not found" >> "$LOG"; exit 0; }
# uname -r can be spoofed (SUSFS CONFIG_KSU_SUSFS_SPOOF_UNAME), so read the real
# release straight from init_uts_ns instead.
EXPECTED=$(cat "$MODDIR/kernel.release" 2>/dev/null || true)
CURRENT=$(cat /proc/sys/kernel/osrelease 2>/dev/null || uname -r)
# The kernel compares vermagic with same_magic(), which drops the release part
# entirely once a module carries CRCs (kernel/module/version.c). Require the base
# version to match; a differing build suffix is only noted.
if [ -z "$EXPECTED" ] || [ "${EXPECTED%%-*}" != "${CURRENT%%-*}" ]; then
  echo "wifi-lkm: kernel mismatch: built for '$EXPECTED', running '$CURRENT' (uname -r reports '$(uname -r)')" >> "$LOG"
  exit 1
fi
[ "$EXPECTED" = "$CURRENT" ] || echo "wifi-lkm: build suffix differs, continuing: '$EXPECTED' vs '$CURRENT'" >> "$LOG"
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
