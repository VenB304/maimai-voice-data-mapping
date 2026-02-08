# Batch Extraction Script

$rootPath = "d:\maimai circle voice and partner data"
$toolPath = Join-Path $rootPath "CriTools-master\src\index.js"
$key = "9170825592834449000"

# Find all .acb files in 'Voice_Partner_*' and 'Voice' directories
$acbFiles = Get-ChildItem -Path $rootPath -Recurse -Filter *.acb

foreach ($file in $acbFiles) {
    if ($file.FullName -notmatch "CriTools-master") {
        Write-Host "Processing $($file.Name)..."
        
        # New structure: d:\data\Voice_Partner_000001\Voice_Partner_000001.acb
        # Output to: d:\data\Voice_Partner_000001\Voice_Partner_000001_extracted
        
        $outputDir = Join-Path $file.Directory.FullName ($file.BaseName + "_extracted")
        if (-not (Test-Path $outputDir)) {
            New-Item -ItemType Directory -Path $outputDir | Out-Null
        }

        $argumentList = @("`"$toolPath`"", "acb2hcas", "-d", "-k", "$key", "`"$($file.FullName)`"")
        
        # Execute node command
        Start-Process -FilePath "node" -ArgumentList $argumentList -Wait -NoNewWindow
        
        Write-Host "Finished $($file.Name)"
    }
}
