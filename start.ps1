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

$python=@(
  (Join-Path $root '.venv\Scripts\python.exe'),
  (Join-Path $root 'backend\.venv\Scripts\python.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if(-not(Test-Path $python)){throw '请先执行 python -m venv .venv，并安装 backend\requirements.txt'}
$ragSetup = Join-Path $root 'scripts\setup_rag_models.py'
& $python $ragSetup
if($LASTEXITCODE -ne 0){throw 'RAG 模型准备失败，请手动运行 scripts/setup_rag_models.py 并检查输出'}
# Auto-detect GPT-SoVITS root from environment or standard locations
$gptRoot = $env:GPT_SOVITS_ROOT
if (-not $gptRoot) {
  $candidates = @(
    'GPT-SoVITS-v2pro-20250604',
    'GPT-SoVITS',
    'gpt-sovits'
  ) | ForEach-Object { Join-Path (Split-Path $root) $_ }
  $gptRoot = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
$nltkData=Join-Path $gptRoot 'nltk_data'
if(Test-Path $nltkData){$env:NLTK_DATA=$nltkData}
# New package layout: runtime\python.exe (not .venv\Scripts\python.exe)
$gptPython = @(
  (Join-Path $gptRoot 'runtime\python.exe'),
  (Join-Path $gptRoot '.venv\Scripts\python.exe'),
  (Join-Path $gptRoot '.venv\bin\python')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$gptConfig=Join-Path $gptRoot 'GPT_SoVITS\configs\tts_infer.yaml'
$baseGpt=Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\s1v3.ckpt'
$baseSovits=Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\v2Pro\s2Gv2ProPlus.pth'
$gptAvailable=$false
if($gptPython -and (Test-Path $gptConfig)) {
  $gptRequired=@(
    $baseGpt,
    $baseSovits,
    (Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\v2Pro\s2Dv2Pro.pth'),
    (Join-Path $gptRoot 'GPT_SoVITS\pretrained_models\sv\pretrained_eres2netv2w24s4ep4.ckpt')
  )
  $gptAvailable=(($gptRequired | Where-Object { -not (Test-Path $_) }).Count -eq 0)
  if(-not $gptAvailable){
    Write-Warning 'GPT-SoVITS files are incomplete; skipping the optional local GPT-SoVITS process.'
  } else {
    # Verify tts_infer.yaml custom section points to existing weights
    $yamlContent = Get-Content $gptConfig -Raw
    if ($yamlContent -match 't2s_weights_path:\s*(.+)') {
      $t2sRelPath = $matches[1].Trim()
      # Check if path is absolute or relative
      if ([System.IO.Path]::IsPathRooted($t2sRelPath)) {
        $t2sPath = $t2sRelPath
      } else {
        $t2sPath = Join-Path $gptRoot $t2sRelPath
      }
      if (-not (Test-Path $t2sPath)) {
        Write-Warning "Custom t2s_weights_path not found: $t2sPath. Backing up and fixing config..."
        Copy-Item $gptConfig "$gptConfig.bak.$(Get-Date -Format yyyyMMddHHmmss)"
        $yamlContent = $yamlContent -replace 't2s_weights_path:\s*.+', "t2s_weights_path: GPT_SoVITS/pretrained_models/s1v3.ckpt"
        $yamlContent = $yamlContent -replace 'vits_weights_path:\s*.+', "vits_weights_path: GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth"
        $yamlContent | Set-Content $gptConfig -NoNewline
        Write-Output "Fixed tts_infer.yaml to use base weights"
      }
    }
  }
}
$gptLauncher=Join-Path $root 'scripts\gpt_sovits_api.py'
if($gptAvailable){
  # Upgrade an already running project api_v2.py process in place. Without
  # this, the launcher would reject its own old process as a foreign port
  # owner and the reference-cache/streaming fix would never take effect.
  foreach($process in @(Get-ListeningProcesses 9881)) {
    $commandLine = [string]$process.CommandLine
    if($commandLine -like "*$gptRoot*" -and $commandLine -match 'api_v2\.py') {
      Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
  }
  for($i = 0; $i -lt 40 -and (Test-ListeningPort 9881); $i++) {
    Start-Sleep -Milliseconds 250
  }
  if(-not (Assert-PortOwner 9881 $gptPython $gptLauncher 'GPT-SoVITS')){
  # This entry point installs reference caching and bounded streaming chunks.
  # Starting api_v2.py directly silently bypasses both latency optimizations.
  $gptArguments=@(('"' + $gptLauncher + '"'),'--gpt-root',('"' + $gptRoot + '"'),'-a','127.0.0.1','-p','9881','-c','GPT_SoVITS/configs/tts_infer.yaml')
  Start-Process -FilePath $gptPython -ArgumentList $gptArguments -WorkingDirectory $gptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'gpt-runtime.log') -RedirectStandardError (Join-Path $root 'gpt-runtime-error.log')
  }
}
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
  if(-not (Wait-ListeningPort 9881 180)){
    Write-Warning 'GPT-SoVITS 9881 is still loading; the browser fallback remains available.'
  } else {
    # The backend owns weight changes under its inference lock and recognizes
    # weights already loaded by the runtime. Reloading them here races startup
    # warmup, discards its reference cache and delays the first live request.
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
