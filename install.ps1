param(
    [string]$InstallRoot = (Join-Path $HOME ".agents\skills\deepseek-cowork"),
    [string]$ConfigPath = (Join-Path $HOME ".codex\deepseek-cowork\config.toml")
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "skill"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Recurse -Force (Join-Path $source "*") $InstallRoot

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $ConfigPath) | Out-Null
$config = @'
api_key = "REPLACE_ME"
base_url = "https://api.deepseek.com"

[models]
fast = "deepseek-v4-flash"
reasoning = "deepseek-v4-pro"

[runtime]
max_revision_rounds = 3
timeout_seconds = 180
transient_retries = 2

[verification]
commands = []
'@
    [System.IO.File]::WriteAllText(
        $ConfigPath,
        $config,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

icacls $ConfigPath /inheritance:r /grant:r "$($env:USERNAME):(F)" "SYSTEM:(F)" | Out-Null
Write-Host "Installed Skill: $InstallRoot"
Write-Host "Config: $ConfigPath"
