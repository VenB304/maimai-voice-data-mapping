$rootPath = "d:\maimai circle voice and partner data"
$toolPath = Join-Path $rootPath "CriTools-master\src\index.js"
# Find all .acb files
$acbFiles = Get-ChildItem -Path $rootPath -Recurse -Filter *.acb

foreach ($file in $acbFiles) {
    if ($file.FullName -NOTMATCH "CriTools-master") {
        Write-Host "Extracting metadata for $($file.Name)..."
        # Run view_utf to get json
        # Command: node index.js view_utf <acb_file>
        # Output is usually printed to stdout, so we redirect it
        
        $jsonPath = [System.IO.Path]::ChangeExtension($file.FullName, ".json")
        # Use -o to output directly to file, preventing log messages from corrupting the JSON
        $argumentList = @("`"$toolPath`"", "view_utf", "-o", "`"$jsonPath`"", "`"$($file.FullName)`"")
        
        # Run process
        Start-Process -FilePath "node" -ArgumentList $argumentList -Wait -NoNewWindow
        
        Write-Host "Created $jsonPath"
    }
}
