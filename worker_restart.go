package main

import "strings"

// Both the launcher and Windows replacement check use this list. Keeping a
// second hard-coded list caused upgrades from 0.6.5 to fail on Windows.
var legacyClipsVersions = []string{"0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.6.1", "0.6.2", "0.6.3", "0.6.4", "0.6.5"}

func isLegacyClipsVersion(version string) bool {
	for _, known := range legacyClipsVersions {
		if version == known {
			return true
		}
	}
	return false
}

func legacyWorkerStopScript() string {
	quoted := make([]string, len(legacyClipsVersions))
	for i, version := range legacyClipsVersions {
		quoted[i] = "'" + version + "'"
	}
	return strings.Replace(legacyWorkerStopTemplate, "__LEGACY_VERSIONS__", strings.Join(quoted, ","), 1)
}

const legacyWorkerStopTemplate = `$ErrorActionPreference='Stop'
$base='http://127.0.0.1:8765'
$status=Invoke-RestMethod "$base/api/status" -TimeoutSec 3
if($status.version -notin @(__LEGACY_VERSIONS__) -or $status.render_engine -notin @('FFmpeg required','FFmpeg') -or $status.post_safety -ne 'consent per destination'){throw 'Unexpected local service'}
$queue=Invoke-RestMethod "$base/api/queue" -TimeoutSec 3
if($queue | Where-Object {$_.status -in @('sending','submitting','publishing')}){exit 42}
$connection=Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen
if(@($connection).Count -ne 1){throw 'Unexpected listener'}
$worker=Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
$session=(Get-Process -Id $PID).SessionId
if($worker.SessionId -ne $session -or $worker.CommandLine -notmatch '\s-m uvicorn server:app --host 127\.0\.0\.1 --port 8765 --no-access-log\s*$'){throw 'Unexpected worker process'}
Stop-Process -Id $worker.ProcessId -ErrorAction Stop
for($attempt=0;$attempt -lt 30;$attempt++){
  if(-not (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)){exit 0}
  Start-Sleep -Milliseconds 100
}
throw 'Worker address did not release'
`
