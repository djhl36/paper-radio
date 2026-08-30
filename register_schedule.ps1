# 매주 월요일 오전 7시에 논문 라디오 파이프라인을 자동 실행하는 작업 등록
$python = (Get-Command python).Source
$script = Join-Path $PSScriptRoot "run_pipeline.py"
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "PaperRadioPipeline" -Action $action -Trigger $trigger -Settings $settings -Description "논문 라디오: 논문 수집·요약·오디오 자동 생성" -Force
Write-Host "등록 완료: 매주 월요일 07:00에 실행됩니다. (작업 스케줄러에서 'PaperRadioPipeline' 확인)"
