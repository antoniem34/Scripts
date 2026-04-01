$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Start-Process pythonw -ArgumentList "`"$root\background_removal_app.py`""
