#!/usr/bin/env bash
# Install Airflow scheduler + webserver as systemd services.
# Run later with: sudo ./install.sh
# Only after the interactive scheduler has been stopped and the daily queue is idle.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIRFLOW_HOME=/home/khaliq/airflow_project/airflow
DB="$AIRFLOW_HOME/airflow.db"
PY=/home/khaliq/airflow_project/venv/bin/python
UNITS=(airflow-scheduler.service airflow-webserver.service)

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run with sudo: sudo $0" >&2
  exit 1
fi

for u in "${UNITS[@]}"; do
  if [[ ! -f "$DEPLOY_DIR/$u" ]]; then
    echo "ERROR: missing unit file: $DEPLOY_DIR/$u" >&2
    exit 1
  fi
done

# 1) Refuse if an 'airflow scheduler' process is running outside systemd.
# Inspect /proc directly so this check cannot match itself (unlike pgrep -f).
stray=()
for proc in /proc/[0-9]*; do
  pid="${proc#/proc/}"
  cmdline="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
  case "$cmdline" in
    *'airflow scheduler'*)
      ;;
    *)
      continue
      ;;
  esac
  # Skip this installer and obvious search tools
  case "$cmdline" in
    *install.sh*|*'systemd-analyze'*|*'pgrep '*|*'grep '*)
      continue
      ;;
  esac
  cg="$(cat "$proc/cgroup" 2>/dev/null || true)"
  if ! grep -q 'airflow-scheduler.service' <<<"$cg"; then
    stray+=("$pid")
  fi
done
if ((${#stray[@]} > 0)); then
  echo "ERROR: an 'airflow scheduler' process not owned by systemd is still running (PIDs: ${stray[*]})." >&2
  echo "Stop it with Ctrl+C in its terminal, wait for it to exit, then re-run." >&2
  ps -o pid,user,stat,lstart,cmd -p "$(IFS=,; echo "${stray[*]}")" >&2 || true
  exit 1
fi

# 2) Refuse if any task_instance is running or queued (read-only SQLite).
if [[ ! -x "$PY" ]]; then
  echo "ERROR: python not found at $PY" >&2
  exit 1
fi
if [[ ! -f "$DB" ]]; then
  echo "ERROR: Airflow DB not found at $DB" >&2
  exit 1
fi
active="$("$PY" - "$DB" <<'PYEOF'
import sqlite3
import sys

con = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
rows = con.execute(
    "SELECT dag_id, task_id, state FROM task_instance "
    "WHERE state IN ('running', 'queued') "
    "ORDER BY dag_id, task_id"
).fetchall()
for dag_id, task_id, state in rows:
    print("  %s.%s [%s]" % (dag_id, task_id, state))
PYEOF
)" || {
  echo "ERROR: could not query $DB read-only." >&2
  exit 1
}
if [[ -n "$active" ]]; then
  echo "ERROR: tasks still running or queued; wait for the queue to finish:" >&2
  echo "$active" >&2
  exit 1
fi

# 3) Remove stale webserver pidfile, install units, enable and start.
rm -f "$AIRFLOW_HOME/airflow-webserver.pid"
for u in "${UNITS[@]}"; do
  install -m 0644 -o root -g root "$DEPLOY_DIR/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable --now "${UNITS[@]}"

# 4) Print status and hit the health endpoint.
sleep 10
systemctl --no-pager --full status "${UNITS[@]}" || true
echo "--- curl http://127.0.0.1:8080/health ---"
if curl -fsS --max-time 5 http://127.0.0.1:8080/health; then
  echo
else
  echo "webserver not ready yet; retrying a few times (first start can take a minute)..."
  ok=0
  for _ in 1 2 3 4 5 6; do
    sleep 15
    if curl -fsS --max-time 5 http://127.0.0.1:8080/health; then
      echo
      ok=1
      break
    fi
    echo "not ready yet..."
  done
  if [[ $ok -eq 0 ]]; then
    echo "WARNING: http://127.0.0.1:8080/health did not respond. Check: journalctl -u airflow-webserver -n 80" >&2
    exit 1
  fi
fi
