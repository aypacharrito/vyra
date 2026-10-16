//go:build windows

package main

import (
	"context"
	"errors"
	"os/exec"
	"time"
)

// Older releases left their Python worker running after closing the desktop.
// Verify its VYRA status, exact launch arguments and Windows session before
// replacing it, and leave a publishing worker alone until submission finishes.
func stopLegacyWorker() error {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	script := `$ErrorActionPreference='Stop'
$base='http://127.0.0.1:8765'
$status=Invoke-RestMethod "$base/api/status" -TimeoutSec 3
if($status.version -notin @('0.3.0','0.4.0') -or $status.render_engine -ne 'FFmpeg required' -or $status.post_safety -ne 'consent per destination'){throw 'Unexpected local service'}
$queue=Invoke-RestMethod "$base/api/queue" -TimeoutSec 3
if($queue | Where-Object {$_.status -in @('sending','submitting','publishing')}){throw 'Publishing is still active'}
$connection=Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen
if(@($connection).Count -ne 1){throw 'Unexpected listener'}
$worker=Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
$session=(Get-Process -Id $PID).SessionId
if($worker.SessionId -ne $session -or $worker.CommandLine -notmatch '\s-m uvicorn server:app --host 127\.0\.0\.1 --port 8765 --no-access-log\s*$'){throw 'Unexpected worker process'}
Stop-Process -Id $worker.ProcessId -ErrorAction Stop
`
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script)
	hideWorker(cmd)
	if err := cmd.Run(); err != nil {
		return errors.New("An older Clips worker is still active. Finish any publishing, then reload the studio.")
	}
	return nil
}
