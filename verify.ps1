$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw '未找到项目虚拟环境 .venv' }

Push-Location $root
try {
  & $python -m pytest backend/tests -q
  if ($LASTEXITCODE -ne 0) { throw '后端自动测试失败，停止验收' }
  $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health'
  $status = Invoke-RestMethod 'http://127.0.0.1:8000/api/tts/status'
  if (-not $status.ready) { throw 'TTS is not ready; run start.ps1 and configure a usable clone voice first' }
  if ($status.warming_up) { throw 'TTS is still warming up; wait for start.ps1 to finish before verification' }
  $retrieval = Invoke-RestMethod 'http://127.0.0.1:8000/api/tests/retrieval' -Method Post
  $qa = Invoke-RestMethod 'http://127.0.0.1:8000/api/tests/qa' -Method Post
  $tts = Invoke-RestMethod 'http://127.0.0.1:8000/api/tests/tts' -Method Post
  $voices = Invoke-RestMethod 'http://127.0.0.1:8000/api/voices'
  $readyClone = @($voices | Where-Object { $_.cloned -eq 1 -and $_.quality.status -eq 'ready' }).Count
  [pscustomobject]@{
    service = $health.status
    tts_ready = $status.ready
    retrieval = "$($retrieval.passed)/$($retrieval.total)"
    retrieval_accuracy = $retrieval.accuracy
    retrieval_target = $retrieval.meets_target
    qa = "$($qa.passed)/$($qa.total)"
    qa_accuracy = $qa.accuracy
    qa_target = $qa.meets_target
    qa_scope = '本地回答样本自测；85%为项目自测目标，不是赛题额外硬门槛'
    tts_average_first_audio_ms = $tts.average_first_audio_ms
    tts_target = $tts.meets_target
    tts_scope = '模型就绪后的后端首 PCM；浏览器输出延迟请参阅三轮验收报告'
    ready_cloned_voices = $readyClone
  } | ConvertTo-Json
  if (-not $retrieval.meets_target -or -not $qa.meets_target -or -not $tts.meets_target) { throw '项目自测未通过，请查看各项结果及测量范围' }
} finally {
  Pop-Location
}
