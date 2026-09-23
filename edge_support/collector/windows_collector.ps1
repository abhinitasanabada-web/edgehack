param(
    [string]$ApiUrl = "http://127.0.0.1:8502",
    [Parameter(Mandatory=$true)][string]$Complaint,
    [switch]$AutoApply,
    [switch]$Confirmed
)

$ErrorActionPreference = "Stop"

function Get-EndpointTelemetry {
    $dnsOk = $true
    try { Resolve-DnsName example.com -ErrorAction Stop | Out-Null } catch { $dnsOk = $false }
    $processes = Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20 `
        @{Name="name";Expression={$_.ProcessName}},
        @{Name="memory_mb";Expression={[math]::Round($_.WorkingSet64 / 1MB, 1)}},
        @{Name="cpu_seconds";Expression={$_.CPU}}
    $drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    return @{
        cpu_percent = $null
        memory_percent = $null
        disk_percent = [math]::Round((1 - ($drive.FreeSpace / $drive.Size)) * 100, 2)
        processes = @($processes)
        network = @{ dns_ok = $dnsOk }
        collected_at = (Get-Date).ToUniversalTime().ToString("o")
    }
}

function Invoke-ApprovedAction([string]$ActionId, $Telemetry) {
    switch ($ActionId) {
        "flush_dns" { ipconfig /flushdns; return "DNS cache flushed" }
        "restart_dns_client" { Restart-Service -Name Dnscache; return "DNS Client service restarted" }
        "clear_temp" { $safeRoot = Join-Path $env:TEMP "EdgeSupportSafeTemp"; if (Test-Path $safeRoot) { Remove-Item "$safeRoot\*" -Recurse -Force }; return "Approved temp workspace cleared" }
        "close_demo_process" {
            $allowed = @("notepad", "calculatorapp", "mspaint")
            $candidate = $Telemetry.processes | Where-Object { $allowed -contains $_.name.ToLower() } | Select-Object -First 1
            if ($null -eq $candidate) { throw "No allowlisted demo process was found" }
            Stop-Process -Name $candidate.name -Force
            return "Allowlisted demo process closed"
        }
        default { return "No endpoint change requested" }
    }
}

$before = Get-EndpointTelemetry
$request = @{ complaint = $Complaint; telemetry = $before } | ConvertTo-Json -Depth 8
$diagnosis = Invoke-RestMethod -Uri "$ApiUrl/diagnose" -Method Post -ContentType "application/json" -Body $request
$diagnosis | ConvertTo-Json -Depth 8

if ($AutoApply -and $Confirmed -and -not $diagnosis.diagnosis.escalate -and $diagnosis.diagnosis.recommended_action -ne "no_action_escalate") {
    $actionId = $diagnosis.diagnosis.recommended_action
    try {
        $message = Invoke-ApprovedAction $actionId $before
        $after = Get-EndpointTelemetry
        $verification = @{ action_id = $actionId; before = $before; after = $after } | ConvertTo-Json -Depth 8
        Invoke-RestMethod -Uri "$ApiUrl/verify" -Method Post -ContentType "application/json" -Body $verification | ConvertTo-Json -Depth 8
        Write-Host "Action: $message"
    } catch {
        Write-Error "Approved action failed: $($_.Exception.Message)"
    }
}
