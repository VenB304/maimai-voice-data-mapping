
$rootDir = "d:\maimai circle voice and partner data"
$outputBase = Join-Path $rootDir "Renamed_Voice"
$partnerMappingRoot = Join-Path $rootDir "partner_mapping"

New-Item -ItemType Directory -Force -Path $outputBase | Out-Null

# --- Helper: Parse Partner XML ---
function Get-PartnerMapping ($partnerId) {
    # PartnerId format: '000001'
    # Look for folder partner000001 in partner_mapping
    $pDir = Join-Path $partnerMappingRoot ("partner" + $partnerId)
    $xmlPath = Join-Path $pDir "Partner.xml"
    
    if (-not (Test-Path $xmlPath)) { return $null }
    
    [xml]$xml = Get-Content $xmlPath -Encoding UTF8
    $data = @{
        NameJP = $xml.PartnerData.name.str
        Events = @{}
    }
    
    $xml.PartnerData.ChildNodes | ForEach-Object {
        $val = $_.InnerText
        if ($val -match "^VO_\d+$") {
            $data.Events[$val] = $_.Name # VO_000001 = partnerRoomEntryVoice
        }
    }
    return $data
}

# --- Helper: Parse Cue JSON ---
function Get-CueMapping ($jsonPath) {
    if (-not (Test-Path $jsonPath)) { return $null }
    
    try {
        $jsonContent = Get-Content $jsonPath -Raw -Encoding UTF8
        $json = $jsonContent | ConvertFrom-Json
        
        # Structure varies slightly or is array. Usually an array where one item has CueNameTable.
        if ($json -is [array]) {
            $root = $json | Where-Object { $_.CueNameTable -ne $null } | Select-Object -First 1
        } else {
            $root = $json
        }
        
        $map = @{}
        if ($root -and $root.CueNameTable) {
            foreach ($cue in $root.CueNameTable) {
                $map[$cue.CueIndex] = $cue.CueName # 0 = VO_000080
            }
        }
        return $map
    } catch {
        Write-Host "Error parsing JSON $jsonPath" -ForegroundColor Red
        return $null
    }
}

# --- Processing Partners ---
$partnerDirs = Get-ChildItem -Path $rootDir -Directory -Filter "Voice_Partner_*"
foreach ($dir in $partnerDirs) {
    $id = $dir.Name -replace "Voice_Partner_", ""
    $jsonPath = Join-Path $dir.FullName ($dir.Name + ".json")
    
    # Locate Audio
    # Check regular extracted folder or nested folder
    $audioDir = Join-Path $dir.FullName $dir.Name # Nested
    if (-not (Test-Path $audioDir)) {
         # Fallback to local if checking behavior was wrong (or if acb2hcas changed behavior)
         $audioDir = $dir.FullName 
    }
    
    Write-Host "Processing Partner $id..."
    
    # Get Mappings
    $partnerData = Get-PartnerMapping -partnerId $id
    $cueMap = Get-CueMapping -jsonPath $jsonPath
    
    if (-not $partnerData) {
        Write-Host "  No Partner.xml found. Skipping rename logic (will just copy)." -ForegroundColor Yellow
        $destDir = Join-Path $outputBase "Unknown_Partner_$id"
    } else {
        $cleanName = $partnerData.NameJP -replace "[\\/:\*\?`"<>\|]", "_"
        $destDir = Join-Path $outputBase "partner${id}-${cleanName}"
    }
    
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    
    # Process Files
    if ($cueMap) {
        $cueMap.Keys | ForEach-Object {
            $idx = $_
            $voId = $cueMap[$idx]
            
            # Source File: stream_{idx}.hca
            $srcFile = Join-Path $audioDir "stream_${idx}.hca"
            
            if (Test-Path $srcFile) {
                # Determine Name
                $eventName = $null
                if ($partnerData -and $partnerData.Events.ContainsKey($voId)) {
                    $eventName = $partnerData.Events[$voId]
                    $destName = "${voId}_${eventName}.hca"
                } else {
                    $destName = "${voId}.hca"
                }
                
                Copy-Item -Path $srcFile -Destination (Join-Path $destDir $destName) -Force
            }
        }
    } else {
        Write-Host "  No JSON Queue Map found/parsed. Skipping." -ForegroundColor Red
    }
}

# --- Processing System Voice ---
$voiceDir = Join-Path $rootDir "Voice"
if (Test-Path $voiceDir) {
    Write-Host "Processing System Voice..."
    $jsonPath = Join-Path $voiceDir "Voice_000001.json"
    $audioDir = Join-Path $voiceDir "Voice_000001" # Nested assumption
    
    $cueMap = Get-CueMapping -jsonPath $jsonPath
    $destDir = Join-Path $outputBase "System_Voice"
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    
    if ($cueMap) {
        $cueMap.Keys | ForEach-Object {
            $idx = $_
            $voId = $cueMap[$idx]
            $srcFile = Join-Path $audioDir "stream_${idx}.hca"
            
            if (Test-Path $srcFile) {
                Copy-Item -Path $srcFile -Destination (Join-Path $destDir "${voId}.hca") -Force
            }
        }
    }
}

Write-Host "Renaming Complete."
