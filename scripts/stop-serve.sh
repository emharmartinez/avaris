#!/usr/bin/env bash
# Stops the `avaris serve` the launcher started (avaris-launch.ps1 -Stop), from the repo root.
# A server that stopped itself (idle shutdown, the app's Stop button) leaves data/serve.pid
# behind: kill only while that pid is still an avaris serve (global options may sit between). A file, not an inline command,
# because Windows PowerShell 5.1 splits arguments with embedded quotes before wsl.exe
pid=$(cat data/serve.pid 2>/dev/null)
if [ -n "$pid" ] && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qE 'avaris .*serve( |$)'; then
  kill "$pid"
  rm -f data/serve.pid
else
  rm -f data/serve.pid
  echo "No launcher-started server is running"
  exit 1
fi
