param(
    [ValidateSet('Start', 'Stop', 'InstallStartup', 'RemoveStartup')]
    [string]$Action = 'Start'
)

$ErrorActionPreference = 'Stop'
$marker = 'property-concierge-wsl-keepalive'
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Property Concierge Docker.lnk'

function Get-KeepAliveProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
        Where-Object { $_.CommandLine -like "*$marker*" }
}

if ($Action -eq 'RemoveStartup') {
    if (Test-Path -LiteralPath $startupLink) {
        Remove-Item -LiteralPath $startupLink
    }
    Write-Output 'Login startup removed. Use -Action Stop to stop the current helper.'
    exit
}

if ($Action -eq 'Stop') {
    # 다른 프로젝트의 WSL 세션이나 컨테이너는 직접 종료하지 않는다.
    Get-KeepAliveProcess | ForEach-Object { Stop-Process -Id $_.ProcessId }
    Write-Output 'WSL keep-alive helper stopped.'
    exit
}

if ($Action -eq 'InstallStartup') {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($startupLink)
    $shortcut.TargetPath = Join-Path $PSHOME 'powershell.exe'
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '"'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Keep local WSL Docker available for Property Concierge'
    $shortcut.Save()
    Write-Output 'Current-user login startup installed.'
}

# systemd의 Docker 서비스만으로는 WSL 유휴 종료를 막지 못하므로
# Windows에서 실행한 WSL 세션 하나를 유지한다. 중복 실행은 피한다.
if (-not (Get-KeepAliveProcess)) {
    $helper = Start-Process -FilePath "$env:WINDIR\System32\wsl.exe" `
        -ArgumentList '--distribution Ubuntu --exec sh -c "exec sleep infinity" property-concierge-wsl-keepalive' `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    if ($helper.HasExited) {
        throw 'WSL keep-alive failed to start. Check the Ubuntu distribution.'
    }
    Write-Output "WSL keep-alive started (PID $($helper.Id))."
} else {
    Write-Output 'WSL keep-alive is already running.'
}
