# Persistent runner launcher for STEP 14
$RepoRoot = (Resolve-Path .).Path
$VenvPython = Join-Path $RepoRoot ".venv2\Scripts\python.exe"
$Runner = Join-Path $RepoRoot "video_pipeline_v2\runtime\qualification_runner.py"

# Launch background process
$Process = Start-Process -FilePath $VenvPython -ArgumentList $Runner,"preflight" -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RepoRoot "artifacts\gpu_video_pipeline_v2\step14\process_runner\smoke_stdout.log") -RedirectStandardError (Join-Path $RepoRoot "artifacts\gpu_video_pipeline_v2\step14\process_runner\smoke_stderr.log")

# Persist metadata
$Meta = @{
    pid = $Process.Id
    ppid = (Get-Process -Id $Process.Id).Parent.Id
    python_executable = $VenvPython
    command_line = "python $Runner preflight"
    working_directory = $RepoRoot
    launcher = "run_step14.ps1"
}
$Meta | ConvertTo-Json | Out-File (Join-Path $RepoRoot "artifacts\gpu_video_pipeline_v2\step14\process_runner\launcher.json") -Encoding utf8

Write-Host "LAUNCHER: PID=$($Process.Id), PPID=$((Get-Process -Id $Process.Id).Parent.Id), python=$VenvPython"
