$ErrorActionPreference = 'Stop'

$baseUrl = 'https://loom42.com'
$outputRoot = Join-Path $PSScriptRoot 'public\template-library\images'
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$categories = (Invoke-RestMethod -Uri "$baseUrl/api/template-categories").data
$records = [System.Collections.Generic.List[object]]::new()

foreach ($category in $categories) {
    $page = 1
    do {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/templates?type=system&category=$($category.category_key)&page=$page&pageSize=60"
        foreach ($template in $response.data) {
            foreach ($slot in $template.slots) {
                if ($slot.display_image_url) {
                    $records.Add([pscustomobject]@{
                        category = $category.label
                        template = $template.name
                        templateId = $template.template_id
                        slot = $slot.index
                        url = $slot.display_image_url
                    })
                }
            }
        }
        $page++
    } while ($response.pagination.hasMore)
}

$unique = $records | Sort-Object url -Unique
$manifest = Join-Path $outputRoot 'manifest.json'
$unique | ConvertTo-Json -Depth 4 | Set-Content -Path $manifest -Encoding utf8

$pending = [System.Collections.Generic.List[object]]::new()
foreach ($item in $unique) {
    $safeCategory = ($item.category -replace '[\\/:*?"<>|]', '_')
    $safeTemplate = ($item.template -replace '[\\/:*?"<>|]', '_')
    $folder = Join-Path (Join-Path $outputRoot $safeCategory) $safeTemplate
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $extension = [IO.Path]::GetExtension(([Uri]$item.url).AbsolutePath)
    if (-not $extension) { $extension = '.jpg' }
    $file = Join-Path $folder ('{0:D2}{1}' -f ([int]$item.slot + 1), $extension)
    if ((Test-Path -LiteralPath $file) -and (Get-Item -LiteralPath $file).Length -gt 0) {
        continue
    }
    $pending.Add([pscustomobject]@{ url = $item.url; file = $file })
}

$done = $unique.Count - $pending.Count
$failed = [System.Collections.Generic.List[string]]::new()
$worker = {
    param($url, $file)
    try {
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        $client = [System.Net.WebClient]::new()
        $client.DownloadFile($url, $file)
        $client.Dispose()
        [pscustomobject]@{ ok = $true; url = $url; error = $null }
    } catch {
        [pscustomobject]@{ ok = $false; url = $url; error = $_.Exception.Message }
    }
}

 $items = @($pending)
for ($offset = 0; $offset -lt $items.Count; $offset += 12) {
    $last = [Math]::Min($offset + 11, $items.Count - 1)
    $batch = $items[$offset..$last]
    $jobs = foreach ($item in $batch) { Start-ThreadJob -ScriptBlock $worker -ArgumentList $item.url, $item.file }
    $results = $jobs | Wait-Job | Receive-Job
    $jobs | Remove-Job -Force
    foreach ($result in $results) {
        if ($result.ok) { $done++ } else { $failed.Add("$($result.url)`t$($result.error)") }
    }
    Write-Progress -Activity 'Downloading Loom42 template images' -Status "$done / $($unique.Count)" -PercentComplete (($done / $unique.Count) * 100)
}

if ($failed.Count) {
    $failed | Set-Content -Path (Join-Path $outputRoot 'failed-downloads.tsv') -Encoding utf8
    throw "Completed $done downloads; $($failed.Count) failed. See failed-downloads.tsv."
}

Write-Output "Downloaded $done images to $outputRoot"
