
$rootDir = "d:\maimai circle voice and partner data"
$toolPath = Join-Path $rootDir "CriTools-master\src\index.js"
$key = "9170825592834449000"

# Target directories: Voice and Voice_Partner_*
$targets = Get-ChildItem -Path $rootDir -Directory | Where-Object { $_.Name -match "^Voice$|^Voice_Partner_\d+" }

foreach ($dir in $targets) {
    $acbFiles = Get-ChildItem -Path $dir.FullName -Filter "*.acb"
    
    foreach ($acb in $acbFiles) {
        Write-Host "Processing $($acb.Name)..."
        
        # 1. Extract Audio (HCA)
        # acb2hcas creates a directory named [ACB_Name] in the same folder
        $argListAudio = @("`"$toolPath`"", "acb2hcas", "-d", "-k", "$key", "`"$($acb.FullName)`"")
        $p1 = Start-Process -FilePath "node" -ArgumentList $argListAudio -Wait -NoNewWindow -PassThru
        
        if ($p1.ExitCode -ne 0) {
             Write-Host "Error extracting audio for $($acb.Name)" -ForegroundColor Red
        } else {
             Write-Host "Audio extracted."
        }

        # 2. Extract Metadata (JSON)
        # Output json to [ACB_Name].json in the same folder
        $jsonPath = [System.IO.Path]::ChangeExtension($acb.FullName, ".json")
        $argListMeta = @("`"$toolPath`"", "view_utf", "-o", "`"$jsonPath`"", "`"$($acb.FullName)`"")
        $p2 = Start-Process -FilePath "node" -ArgumentList $argListMeta -Wait -NoNewWindow -PassThru
        
        if ($p2.ExitCode -ne 0) {
             Write-Host "Error extracting metadata for $($acb.Name)" -ForegroundColor Red
        } else {
             Write-Host "Metadata extracted to $jsonPath"
        }
    }
}
Write-Host "Extraction Phase Complete."
