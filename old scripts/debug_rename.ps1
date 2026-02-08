
$rootDir = "d:\maimai circle voice and partner data"
$pDirName = "partner000001"
$xmlPath = Join-Path $rootDir "Partner\$pDirName\Partner.xml"

[xml]$xml = Get-Content $xmlPath -Encoding UTF8
$eventMap = @{}
$xml.PartnerData.ChildNodes | ForEach-Object {
    if ($_.InnerText -match "^VO_\d+$") {
        $eventMap[$_.InnerText] = $_.Name
        Write-Host "Mapped $($_.InnerText) -> $($_.Name)"
    }
}

$idNum = $pDirName -replace "partner", ""
$jsonPath = Join-Path $rootDir "Partner\Voice_Partner_$idNum.json"
$extractedPath = Join-Path $rootDir "Partner\Voice_Partner_${idNum}_extracted"

Write-Host "JSON Path: $jsonPath"
Write-Host "Extracted Path: $extractedPath"
$json = Get-Content $jsonPath -Raw | ConvertFrom-Json
$cueTable = $json.CueNameTable

$count = 0
foreach ($cue in $cueTable) {
    if ($count -gt 5) { break }
    $voId = $cue.CueName
    $idx = $cue.CueIndex
    $eventName = $eventMap[$voId]
    
    Write-Host "Cue: $voId (Idx: $idx) -> Event: $eventName"
    $count++
}
