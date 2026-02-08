
$rootDir = "d:\maimai circle voice and partner data"
$targetBase = "Voice_Partner_"

# The user mentioned 01 to 35. 
# Based on the file list, we have 01, and then 11 through 35.
# We will just look for any matching files in root and move them.

$files = Get-ChildItem -Path $rootDir -Filter "Voice_Partner_*.acb"

foreach ($file in $files) {
    # Extract the base name (e.g., Voice_Partner_000001)
    $baseName = $file.BaseName
    
    # Create the directory
    $targetDir = Join-Path $rootDir $baseName
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
        Write-Host "Created directory: $targetDir"
    }

    # Move .acb
    $acbPath = $file.FullName
    $destAcb = Join-Path $targetDir $file.Name
    Move-Item -Path $acbPath -Destination $destAcb -Force
    Write-Host "Moved $($file.Name) to $baseName"

    # Move .awb if it exists
    $awbName = $baseName + ".awb"
    $awbPath = Join-Path $rootDir $awbName
    if (Test-Path $awbPath) {
        $destAwb = Join-Path $targetDir $awbName
        Move-Item -Path $awbPath -Destination $destAwb -Force
        Write-Host "Moved $awbName to $baseName"
    }
}
