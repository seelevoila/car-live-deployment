param(
  [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'car-live-agent-startup.lnk'
$taskName = 'CarLiveAgentStartup'
$taskUser = "$env:USERDOMAIN\$env:USERNAME"
$powershellPath = (Get-Command powershell.exe).Source
$scriptPath = Join-Path $root 'start.ps1'

if($Remove){
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  if(Test-Path -LiteralPath $shortcutPath){
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Output "Removed startup shortcut: $shortcutPath"
  } else {
    Write-Output 'Startup shortcut was not installed.'
  }
  Write-Output "Removed logon task: $taskName"
  exit 0
}

$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`" -OpenBrowser -NoWaitTts"
$taskInstalled = $false
try {
  $action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
  $principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  $taskInstalled = $true
  Write-Output "Installed logon task: $taskName"
} catch {
  Write-Warning "Could not install the logon task; using the Startup folder fallback. $($_.Exception.Message)"
}

if($taskInstalled){
  if(Test-Path -LiteralPath $shortcutPath){ Remove-Item -LiteralPath $shortcutPath -Force }
} else {
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $powershellPath
  $shortcut.Arguments = $arguments
  $shortcut.WorkingDirectory = $root
  $shortcut.Description = 'Start the car live agent frontend, backend and TTS services'
  $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
  $shortcut.Save()
  Write-Output "Installed Startup shortcut fallback: $shortcutPath"
}
Write-Output 'Windows will start the services and open http://127.0.0.1:5173 after the next login.'
