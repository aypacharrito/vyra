//go:build !windows

package main

import "errors"

func stopLegacyWorker() error {
	return errors.New("Stop the older Clips worker, then reload the studio.")
}
