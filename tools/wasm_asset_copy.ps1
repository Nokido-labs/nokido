$wslBase = "\\wsl$\Debian\home\user"
$dest = "$env:USERPROFILE\wasmedge"

$searchPaths = @($wslBase, "$wslBase\wasmedge", "$wslBase\llama", "$wslBase\llamaedge", "$wslBase\.wasmedge")
$wasmFiles = @()
$ggufFiles = @()

foreach ($p in $searchPaths) {
    if (Test-Path $p) {
        $wasmFiles += Get-ChildItem $p -Recurse -Filter "*.wasm" -ErrorAction SilentlyContinue
        $ggufFiles += Get-ChildItem $p -Recurse -Filter "*.gguf"  -ErrorAction SilentlyContinue
    }
}

if ($wasmFiles.Count -eq 0 -and $ggufFiles.Count -eq 0) {
    Write-Output "NOT FOUND in common dirs - listing /home/user:"
    Get-ChildItem $wslBase -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_.Name }
    exit 1
}

Write-Output "=== WASM ==="
foreach ($f in $wasmFiles) {
    $mb = [math]::Round($f.Length / 1024 / 1024, 1)
    Write-Output "$($f.FullName) ${mb}MB"
}

Write-Output "=== GGUF ==="
foreach ($f in $ggufFiles) {
    $mb = [math]::Round($f.Length / 1024 / 1024, 1)
    Write-Output "$($f.FullName) ${mb}MB"
}

if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }

foreach ($f in ($wasmFiles + $ggufFiles)) {
    $target = Join-Path $dest $f.Name
    if (-not (Test-Path $target)) {
        $mb = [math]::Round($f.Length / 1024 / 1024, 1)
        Write-Output "Copying $($f.Name) ${mb}MB ..."
        Copy-Item $f.FullName $target
    } else {
        Write-Output "EXISTS: $($f.Name)"
    }
}

Write-Output "=== dest $dest ==="
Get-ChildItem $dest -ErrorAction SilentlyContinue | ForEach-Object {
    $mb = [math]::Round($_.Length / 1024 / 1024, 1)
    Write-Output "$($_.Name) ${mb}MB"
}
