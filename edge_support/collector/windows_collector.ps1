param(
    [string]$ApiUrl = "http://127.0.0.1:8502",
    [Parameter(Mandatory=$true)][string]$Complaint,
    [switch]$AutoApply,
    [switch]$Confirmed
)
# -Confirmed is retained for compatibility, but cannot bypass the per-action prompt.
$ErrorActionPreference = "Stop"
$headers = @{}
if ($env:EDGE_SUPPORT_ACTION_TOKEN) { $headers.Authorization = "Bearer $env:EDGE_SUPPORT_ACTION_TOKEN" }
if ($ApiUrl -notmatch '^https://|^http://(localhost|127\.0\.0\.1)(:|/)') { throw "Use HTTPS or a private loopback SSH tunnel" }

function Get-EndpointTelemetry {
    $dnsOk = $true
    try { Resolve-DnsName example.com -ErrorAction Stop | Out-Null } catch { $dnsOk = $false }
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average
    $processes = Get-Process | Select-Object @{Name="name";Expression={$_.ProcessName}}, @{Name="memory_mb";Expression={[math]::Round($_.WorkingSet64 / 1MB,1)}}
    $drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    # Battery health = full-charge / design capacity (laptops only; $null on desktops or without WMI access).
    $battery = $null
    try {
        $full = (Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -ErrorAction Stop | Select-Object -First 1).FullChargedCapacity
        $design = (Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData -ErrorAction Stop | Select-Object -First 1).DesignedCapacity
        if ($full -and $design) { $battery = [math]::Min(100, [math]::Round(100 * $full / $design, 1)) }
    } catch { $battery = $null }
    # Wi-Fi signal quality from netsh (English-language output); $null when wired or unavailable.
    $wifi = $null
    try {
        $match = (netsh wlan show interfaces) | Select-String '^\s*Signal\s*:\s*(\d+)%' | Select-Object -First 1
        if ($match) { $wifi = [int]$match.Matches[0].Groups[1].Value }
    } catch { $wifi = $null }
    return @{
        cpu_percent = $cpu.Average
        memory_percent = [math]::Round(100 * (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize),2)
        disk_percent = [math]::Round((1 - $drive.FreeSpace / $drive.Size)*100,2)
        battery_health_percent = $battery
        wifi_signal_percent = $wifi
        processes = @($processes | Sort-Object memory_mb -Descending | Select-Object -First 100)
        network = @{dns_ok=$dnsOk}
        collected_at = (Get-Date).ToUniversalTime().ToString("o")
    }
}
$before=Get-EndpointTelemetry
$request=@{complaint=$Complaint;telemetry=$before} | ConvertTo-Json -Depth 8
$result=Invoke-RestMethod -Uri "$ApiUrl/diagnose" -Method Post -Headers $headers -ContentType "application/json" -Body $request -TimeoutSec 3300
$result | ConvertTo-Json -Depth 12
if (-not $AutoApply) { return }
if ($result.simulation -or $result.route.decision -ne "LOCAL" -or -not $result.action_plan.allowed -or $result.diagnosis.escalate -or $result.diagnosis.severity -in @("high","critical")) {
    Write-Host "No action: simulation, escalation, or policy requires review."; return
}
$action=$result.action_plan.action_id
if ($action -ne $result.diagnosis.recommended_action) { throw "Action plan mismatch" }
# Independent endpoint allowlist intentionally narrower than the model's vocabulary.
# Service restarts, file deletion and arbitrary commands are not implemented here.
if ($action -notin @("flush_dns","close_demo_process")) { Write-Host "Manual IT review required for this action."; return }
$target=$null
if ($action -eq "close_demo_process") {
    $target=Read-Host "Enter the demo application to close (notepad, calculatorapp or mspaint). Save work first"
    if ($target -notin @("notepad","calculatorapp","mspaint")) { throw "Process not permitted" }
    $before.target_running=[bool](Get-Process -Name $target -ErrorAction SilentlyContinue)
    if (-not $before.target_running) { throw "Requested process is not running" }
}
$approval=Read-Host "Approve action '$action' on THIS Windows device? Type APPLY"
if ($approval -cne "APPLY") { Write-Host "Cancelled"; return }
$success=$false
if ($action -eq "flush_dns") {
    ipconfig /flushdns
    $success=$LASTEXITCODE -eq 0
} elseif ($action -eq "close_demo_process") {
    # Graceful close preserves the application's save dialog; never force-kill user work.
    Get-Process -Name $target | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    Start-Sleep -Seconds 3
    $success=-not [bool](Get-Process -Name $target -ErrorAction SilentlyContinue)
}
$after=Get-EndpointTelemetry
if ($target) {
    # Verify the exact target even if it falls outside the top-100 telemetry list.
    $before.processes=@(@{name=$target})
    $after.processes=if (Get-Process -Name $target -ErrorAction SilentlyContinue) { @(@{name=$target}) } else { @() }
}
$verification=@{action_id=$action;before=$before;after=$after;target_process=$target;action_success=$success} | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri "$ApiUrl/verify" -Method Post -Headers $headers -ContentType "application/json" -Body $verification | ConvertTo-Json -Depth 8
