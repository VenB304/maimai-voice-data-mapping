
$rootDir = "d:\maimai circle voice and partner data"
$outputDir = Join-Path $rootDir "Renamed_Voice"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

# 1. Process Partner Voices
$partnerDirs = Get-ChildItem -Path (Join-Path $rootDir "partner_mapping") -Directory -Filter "partner*"

foreach ($pDir in $partnerDirs) {
    $xmlPath = Join-Path $pDir.FullName "Partner.xml"
    if (-not (Test-Path $xmlPath)) { continue }

    # Parse XML
    [xml]$xml = Get-Content $xmlPath -Encoding UTF8
    $jpName = $xml.PartnerData.name.str
    $enName = $pDir.Name 

    $targetFolder = Join-Path $outputDir "$enName-$jpName"
    New-Item -ItemType Directory -Force -Path $targetFolder | Out-Null
    Write-Host "Processing: $jpName ($enName)"

    # Create Event Map
    $eventMap = @{}
    $xml.PartnerData.ChildNodes | ForEach-Object {
        if ($_.InnerText -match "^VO_\d+$") {
            $eventMap[$_.InnerText] = $_.Name
        }
    }

    # Find matching JSON and Audio
    $idNum = $pDir.Name -replace "partner", ""
    # JSON and Extracted folder are now in: Voice_Partner_XXXXXX\Voice_Partner_XXXXXX_extracted
    # Need to verify if acb2hcas made a subfolder
    
    $voiceFolder = Join-Path $rootDir "Voice_Partner_$idNum"
    # acb2hcas created a same-named subfolder inside the parent
    $extractedPath = Join-Path $voiceFolder "Voice_Partner_${idNum}"
    
    # We also need the JSON. `extract_all` might not export JSON, only HCA. 
    # We should run extract_metadata.ps1 or rely on existing JSONs if they were moved.
    # Assuming JSONs were NOT moved/created there yet. I will check.
    
    # Check for JSON in the Voice_Partner folder or extracted folder
    $jsonPath = Join-Path $voiceFolder "Voice_Partner_$idNum.json" 

    if (-not (Test-Path $jsonPath) -or -not (Test-Path $extractedPath)) {
        Write-Host "  -> Missing JSON or Extracted Audio for $idNum"
        continue
    }

    # Parse JSON for CueIndex
    $json = Get-Content $jsonPath -Raw | ConvertFrom-Json
    $cueTable = $json.CueNameTable

    foreach ($cue in $cueTable) {
        $voId = $cue.CueName
        $idx = $cue.CueIndex
        $eventName = $eventMap[$voId]

        if (-not $eventName) {
            $eventName = "UnknownEvent"
        }

        # Source File
        $srcFile = Join-Path $extractedPath "stream_$idx.hca"
        
        # Dest File
        $destName = "${voId}_${eventName}.hca"
        $destFile = Join-Path $targetFolder $destName

        if (Test-Path $srcFile) {
            Copy-Item $srcFile $destFile
        } else {
            Write-Host "File not found: $srcFile"
        }
    }
}

# 2. Process System Voice (Voice_000001)
$sysVoiceDir = Join-Path $rootDir "Voice\Voice_000001"
$sysJson = Join-Path $rootDir "Voice\Voice_000001.json"
$sysTarget = Join-Path $outputDir "System_Voice"
New-Item -ItemType Directory -Force -Path $sysTarget | Out-Null

if (Test-Path $sysJson) {
    $json = Get-Content $sysJson -Raw | ConvertFrom-Json
    $cueTable = $json.CueNameTable
    foreach ($cue in $cueTable) {
        $voId = $cue.CueName
        $idx = $cue.CueIndex
        
        $srcFile = Join-Path $sysVoiceDir "stream_$idx.hca"
        $destName = "${voId}.hca"
        $destFile = Join-Path $sysTarget $destName

        if (Test-Path $srcFile) {
            Copy-Item $srcFile $destFile
        }
    }
    Write-Host "Processed System Voices"
}
