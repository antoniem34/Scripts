$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$origen = Read-Host "Carpeta origen"
$destino = Read-Host "Carpeta destino"
$modo = Read-Host "Modo (transparent/canvas) [canvas]"
if ([string]::IsNullOrWhiteSpace($modo)) { $modo = "canvas" }
$limite = Read-Host "Limite de prueba (vacio = todo)"

$args = @(
  "$root\batch_remove_background.py",
  $origen,
  "--output-root", $destino,
  "--model", "birefnet-portrait",
  "--alpha-matting",
  "--autocrop",
  "--output-mode", $modo
)

if ($modo -eq "canvas") {
  $args += @("--canvas-width", "3600", "--canvas-height", "4500", "--subject-height", "4500", "--top-margin", "100")
}

if (-not [string]::IsNullOrWhiteSpace($limite)) {
  $args += @("--limit", $limite)
}

python @args
