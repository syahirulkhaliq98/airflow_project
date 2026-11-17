# Airflow systemd migration (TECH-BOT / WSL Ubuntu)

Staged files in this directory: `airflow-scheduler.service`, `airflow-webserver.service`, `install.sh`.

These units are **not** installed yet. Do not start the services while a crawl is running.

## Install

Do this only in a quiet window, after the day's queue has finished (Grok Bot will ping you).

1. Confirm no task is running or queued.
2. In the PowerShell / WSL window that is running `airflow scheduler`, press **Ctrl+C** and wait until the shell prompt returns.
   Confirm it is gone:

   ```bash
   pgrep -af "airflow scheduler"
   ```

   That command should print nothing.
3. Install and start the services:

   ```bash
   cd /home/khaliq/airflow_project/deploy
   sudo ./install.sh
   ```

   The script refuses to run if a non-systemd scheduler is still running, or if any task is running or queued. It then removes a stale `airflow-webserver.pid`, installs both units, enables and starts them, and prints `systemctl status` plus `curl http://127.0.0.1:8080/health`.
4. Verify:

   ```bash
   systemctl status airflow-scheduler airflow-webserver
   curl http://127.0.0.1:8080/health
   journalctl -u airflow-scheduler -n 50
   journalctl -u airflow-webserver -n 50
   ```

   Recommended after the first successful start: change the Airflow UI admin password. The webserver listens on `0.0.0.0:8080`.

## Rollback

```bash
sudo systemctl disable --now airflow-scheduler airflow-webserver
sudo rm -f /etc/systemd/system/airflow-scheduler.service /etc/systemd/system/airflow-webserver.service
sudo systemctl daemon-reload
```

Then start the scheduler the old way, as `khaliq`, in a terminal you leave open:

```bash
cd /home/khaliq/airflow_project
source venv/bin/activate
export AIRFLOW_HOME=/home/khaliq/airflow_project/airflow
airflow scheduler
```

## Windows follow-ups (already staged, not applied)

- `C:\Users\hcbot\.wslconfig` sets `vmIdleTimeout=-1` so WSL does not idle-shut the VM. It takes effect only after the next `wsl --shutdown` (do that in a quiet window; it stops everything in WSL).
- To auto-start Ubuntu after a Windows reboot, run `C:\Users\hcbot\airflow-deploy\register-wsl-startup.ps1` in PowerShell. It will prompt for the Windows account password and register a startup task. Do not run it until you are ready.
