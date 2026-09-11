param(
  [switch]$OpenBrowser,
  [switch]$NoWaitTts
)

$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$startupLog = Join-Path $root 'startup-runtime.log'
$startupMutex = New-Object System.Threading.Mutex($false, 'Local\CarLiveAgentStartup')
try {
  $startupAcquired = $startupMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
  $startupAcquired = $true
}
if(-not $startupAcquired){
  Write-Output 'Another startup process is already running; using the existing services.'
  exit 0
}

trap {
  $message = "$(Get-Date -Format o) $($_.Exception.Message)"
  Add-Content -LiteralPath $startupLog -Value $message -Encoding UTF8
  try { $startupMutex.ReleaseMutex() } catch {}
  $startupMutex.Dispose()
  [Console]::Error.WriteLine($message)
  exit 1
}

function Test-ListeningPort([int]$port) {
  return @(
    Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  ).Count -gt 0
}

function Get-ListeningProcesses([int]$port) {
  $connections = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
  $processes = @()
  foreach($connection in $connections) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
    if($process) { $processes += $process }
  }
  return $processes
}

function Assert-PortOwner([int]$port, [string]$expectedPython, [string]$expectedCommand, [string]$serviceName) {
  foreach($process in @(Get-ListeningProcesses $port)) {
    $commandMatches = [string]$process.CommandLine -like "*$expectedCommand*"
    $pathMatches = [string]::Equals($process.ExecutablePath, $expectedPython, [StringComparison]::OrdinalIgnoreCase)
    # Windows' venv.exe launcher starts the real base-Python child, and that
    # child owns the socket. Accept it only when its expected venv parent is
    # still present and carries the same service command.
    $parentId = $process.ParentProcessId
    $visited = @{}
    while(-not $pathMatches -and $parentId -and -not $visited.ContainsKey($parentId)) {
      $visited[$parentId] = $true
      $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue
      if(-not $parent) { break }
      if([string]::Equals($parent.ExecutablePath, $expectedPython, [StringComparison]::OrdinalIgnoreCase) -and [string]$parent.CommandLine -like "*$expectedCommand*") {
        $pathMatches = $true
        break
      }
      $parentId = $parent.ParentProcessId
    }
    if(-not ($pathMatches -and $commandMatches)) {
      $details = "PID $($process.ProcessId): $($process.ExecutablePath) $($process.CommandLine)"
      throw "$serviceName 端口 $port 已被非本项目进程占用。请先停止该进程后重试。$([Environment]::NewLine)$details"
    }
  }
  return Test-ListeningPort $port
}

function Wait-ListeningPort([int]$port, [int]$seconds = 12) {
  for($i = 0; $i -lt $seconds * 2; $i++) {
    if(Test-ListeningPort $port){ return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

$ffmpeg='C:\Program Files\CanMV IDE K230\share\qtcreator\ffmpeg\windows\bin'
if(Test-Path $ffmpeg){$env:Path="$ffmpeg;$env:Path"}
$python=@(
  (Join-Path $root '.venv\Scripts\python.exe'),
  (Join-Path $root 'backend\.venv\Scripts\python.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$gptRoot=Join-Path (Split-Path $root) 'GPT-SoVITS'
$nltkData=Join-Path $gptRoot 'nltk_data'
if(Test-Path $nltkData){$env:NLTK_DATA=$nltkData}
$gptPython=Join-Path $gptRoot '.venv\Scripts\python.exe'
$gptConfig=Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\v2Pro\s2Gv2ProPlus.pth'
$baseGpt=Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\s1v3.ckpt'
$baseSovits=Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\v2Pro\s2Gv2ProPlus.pth'
$gptAvailable=$false
if((Test-Path $gptPython) -and (Test-Path $gptConfig)) {
  $gptRequired=@(
    $gptConfig,
    (Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\s1v3.ckpt'),
    (Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\v2Pro\s2Dv2Pro.pth'),
    (Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\sv\pretrained_eres2netv2w24s4ep4.ckpt')
  )
  $gptAvailable=(($gptRequired | Where-Object { -not (Test-Path $_) }).Count -eq 0)
  if(-not $gptAvailable){
    Write-Warning 'GPT-SoVITS files are incomplete; skipping the optional local GPT-SoVITS process.'
  }
}
if($gptAvailable -and -not (Assert-PortOwner 9880 $gptPython 'api_v2.py' 'GPT-SoVITS')){
  Start-Process -FilePath $gptPython -ArgumentList 'api_v2.py','-a','127.0.0.1','-p','9880','-c','GPT_SoVITS/configs/tts_infer.yaml' -WorkingDirectory $gptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'gpt-runtime.log') -RedirectStandardError (Join-Path $root 'gpt-runtime-error.log')
}
if(-not(Test-Path $python)){throw '请先执行 python -m venv .venv，并安装 backend\requirements.txt'}
if(-not (Assert-PortOwner 8000 $python '-m uvicorn app.main:app' '后端')){
  Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'backend-runtime.log') -RedirectStandardError (Join-Path $root 'backend-runtime-error.log')
}
if(-not (Assert-PortOwner 5173 $python '-m http.server 5173' '前端')){
  Start-Process -FilePath $python -ArgumentList '-m','http.server','5173','--bind','127.0.0.1' -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'frontend-runtime.log') -RedirectStandardError (Join-Path $root 'frontend-runtime-error.log')
}
if(-not (Wait-ListeningPort 8000)){ throw '后端 8000 端口未能启动，请查看 backend-runtime-error.log' }
if(-not (Wait-ListeningPort 5173)){ throw '前端 5173 端口未能启动，请查看 frontend-runtime-error.log' }
if($gptAvailable) {
  # The web UI and API are usable while the GPU model is still loading. Do not
  # make a slow model warmup take the whole application offline after reboot.
  if(-not (Wait-ListeningPort 9880 180)){
    Write-Warning 'GPT-SoVITS 9880 is still loading; the browser fallback remains available.'
  } else {
    # GPT-SoVITS stores the active weights globally. Always start from the
    # v2ProPlus base pair; the backend switches to the Xilian fine-tune only for
    # the Xilian voice record, under the TTS inference lock.
    if((Test-Path $baseGpt) -and (Test-Path $baseSovits)) {
      $baseWeightsLoaded=$false
      for($i = 0; $i -lt 60; $i++) {
        try {
          Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:9880/set_gpt_weights' -Method Get -Body @{weights_path=$baseGpt} | Out-Null
          Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:9880/set_sovits_weights' -Method Get -Body @{weights_path=$baseSovits} | Out-Null
          $baseWeightsLoaded=$true
          break
        } catch { Start-Sleep -Seconds 2 }
      }
      if(-not $baseWeightsLoaded){ Write-Warning 'v2ProPlus base weights could not be loaded; backend will retry on first synthesis.' }
    }
    if($NoWaitTts){
      Write-Output 'GPT-SoVITS is starting in the background; browser speech is available during warmup.'
    } else {
      $ttsReady = $false
      $ttsStatus = $null
      for($i = 0; $i -lt 180; $i++) {
        try {
          $ttsStatus = Invoke-RestMethod -UseBasicParsing 'http://127.0.0.1:8000/api/tts/status'
          if($ttsStatus.reachable -and -not $ttsStatus.warming_up){ $ttsReady = [bool]$ttsStatus.ready; break }
        } catch {}
        Start-Sleep -Seconds 1
      }
      if(-not $ttsReady){ Write-Warning 'GPT-SoVITS is running but voice warmup is incomplete; the browser fallback remains available.' }
    }
  }
}
Write-Output 'Frontend: http://127.0.0.1:5173'
Write-Output 'Backend: http://127.0.0.1:8000/docs'
if($OpenBrowser){ Start-Process 'http://127.0.0.1:5173' }
try { $startupMutex.ReleaseMutex() } catch {}
$startupMutex.Dispose()
