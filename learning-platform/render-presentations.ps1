param([string]$PythonPath = "$env:LOCALAPPDATA\EurasiaTeachingPlatform\venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
# Serialise background uploads and the local launcher. Waiting happens only in
# the exporter process; a web request never waits for PowerPoint conversion.
$previewMutex = [Threading.Mutex]::new($false, 'Local\EurasiaTeachingPlatformPresentationPreview')
$ownsMutex = $false
$presentationApp = $null
try {
    try { $ownsMutex = $previewMutex.WaitOne(300000) }
    catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'Another preview export is still running. Missing previews will be retried by the local launcher.' }
    $entries = & $PythonPath (Join-Path $PSScriptRoot 'manage.py') slide_manifest | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the presentation manifest.' }
    if ($entries.Count -eq 0) { Write-Output 'All presentation previews are current.'; return }
    if (Get-Process POWERPNT -ErrorAction SilentlyContinue) { throw 'Close PowerPoint before preparing previews. Existing presentations will not be touched.' }
    $presentationApp = New-Object -ComObject PowerPoint.Application
    # msoAutomationSecurityForceDisable: uploaded presentations cannot run macros.
    $presentationApp.AutomationSecurity = 3
    $presentationApp.DisplayAlerts = 1
    foreach ($entry in $entries) {
        $presentation = $null
        try {
            # ReadOnly=True, Untitled=False, WithWindow=False. Never save the source.
            $presentation = $presentationApp.Presentations.Open($entry.source, -1, 0, 0)
            $slideWidth = 1280
            $slideHeight = [int][Math]::Round($slideWidth * $presentation.PageSetup.SlideHeight / $presentation.PageSetup.SlideWidth)
            $presentation.Export($entry.destination, 'PNG', $slideWidth, $slideHeight)
            $slideCount = $presentation.Slides.Count
            $manifest = @{ count = $slideCount; fingerprint = $entry.fingerprint } | ConvertTo-Json
            [IO.File]::WriteAllText((Join-Path $entry.destination 'manifest.json'), $manifest, [Text.UTF8Encoding]::new($false))
            Write-Output ("Prepared {0}: {1} slides" -f [IO.Path]::GetFileName($entry.source), $slideCount)
        } catch {
            Write-Output ("Could not prepare {0}: {1}" -f [IO.Path]::GetFileName($entry.source), $_.Exception.Message)
        } finally {
            if ($null -ne $presentation) { $presentation.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
        }
    }
} finally {
    if ($null -ne $presentationApp) {
        $presentationApp.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentationApp)
    }
    if ($ownsMutex) { $previewMutex.ReleaseMutex() }
    $previewMutex.Dispose()
}
