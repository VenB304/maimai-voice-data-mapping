
$rootDir = "d:\maimai circle voice and partner data"

# 1. Remove Renamed_Voice directory
$renamedDir = Join-Path $rootDir "Renamed_Voice"
if (Test-Path $renamedDir) {
    Write-Host "Removing $renamedDir..."
    Remove-Item -Path $renamedDir -Recurse -Force
}

# 2. Remove JSON files (excluding those in CriTools or other scripts)
# We strictly target Voice and Voice_Partner folders
$targets = @("Voice", "Voice_Partner_*")
foreach ($t in $targets) {
    $dirs = Get-ChildItem -Path $rootDir -Directory -Filter $t
    foreach ($d in $dirs) {
        # Remove JSONs
        $jsons = Get-ChildItem -Path $d.FullName -Filter "*.json"
        foreach ($j in $jsons) {
            Write-Host "Removing $($j.FullName)..."
            Remove-Item -Path $j.FullName -Force
        }

        # Remove extracted folders (e.g. Voice_Partner_000001 inside Voice_Partner_000001)
        # Note: acb2hcas creates a folder with the same name as the ACB
        $possibleExtractedDir = Join-Path $d.FullName $d.Name
        if (Test-Path $possibleExtractedDir) {
             Write-Host "Removing extracted folder $possibleExtractedDir..."
             Remove-Item -Path $possibleExtractedDir -Recurse -Force
        }
        
        # Also remove _extracted suffix just in case my previous scripts made them
        $suffixDir = Join-Path $d.FullName ($d.Name + "_extracted")
        if (Test-Path $suffixDir) {
             Write-Host "Removing suffix extracted folder $suffixDir..."
             Remove-Item -Path $suffixDir -Recurse -Force
        }
    }
}

Write-Host "Cleanup Complete."
