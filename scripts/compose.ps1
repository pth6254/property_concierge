# WSL Docker와 Windows 작업 폴더를 같은 Compose 프로젝트로 연결한다.
param(
    [ValidateSet('local', 'dev', 'production')][string]$Mode = 'local',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArguments
)
$workspaceRoot = Split-Path $PSScriptRoot -Parent
$linuxRoot = (& wsl wslpath -a -u $workspaceRoot).Trim()
$files = @('-f', "$linuxRoot/infrastructure/compose/compose.yml")
if ($Mode -eq 'dev') { $files += @('-f', "$linuxRoot/infrastructure/compose/compose.override.yml") }
if ($Mode -eq 'production') { $files += @('-f', "$linuxRoot/infrastructure/compose/compose.production.yml") }
& wsl docker compose --project-directory $linuxRoot -p property_concierge @files @ComposeArguments
exit $LASTEXITCODE
