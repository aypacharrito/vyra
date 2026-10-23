//go:build windows

package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"syscall"
	"time"
	"unsafe"
)

var restartKernel = syscall.NewLazyDLL("kernel32.dll")
var restartIPHelper = syscall.NewLazyDLL("iphlpapi.dll")
var restartNTDLL = syscall.NewLazyDLL("ntdll.dll")

func listeningWorkerPID(port int) (uint32, error) {
	var size uint32
	proc := restartIPHelper.NewProc("GetExtendedTcpTable")
	code, _, _ := proc.Call(0, uintptr(unsafe.Pointer(&size)), 0, 2, 3, 0) // AF_INET, TCP_TABLE_OWNER_PID_LISTENER
	if code != 122 && code != 0 {
		return 0, errors.New("Windows could not inspect the Clips listener")
	}
	for attempt := 0; attempt < 3; attempt++ {
		if size < 4 || size > 16<<20 {
			return 0, errors.New("Invalid Windows listener table")
		}
		table := make([]byte, size)
		code, _, _ = proc.Call(uintptr(unsafe.Pointer(&table[0])), uintptr(unsafe.Pointer(&size)), 0, 2, 3, 0)
		if code == 122 {
			continue
		}
		if code != 0 {
			return 0, errors.New("Windows could not inspect the Clips listener")
		}
		return workerPIDFromTCPTable(table, port)
	}
	return 0, errors.New("The Clips listener changed while checking it; try again")
}

func processSession(pid uint32) (uint32, error) {
	var session uint32
	ok, _, err := restartKernel.NewProc("ProcessIdToSessionId").Call(uintptr(pid), uintptr(unsafe.Pointer(&session)))
	if ok == 0 {
		return 0, err
	}
	return session, nil
}

func processArguments(handle uintptr) ([]string, error) {
	// Query the held process handle, avoiding WMI, PowerShell and a PID reuse race.
	var size uint32
	query := restartNTDLL.NewProc("NtQueryInformationProcess")
	query.Call(handle, 60, 0, 0, uintptr(unsafe.Pointer(&size))) // ProcessCommandLineInformation
	if size < 16 || size > 1<<20 {
		return nil, errors.New("Windows could not read the previous Clips command")
	}
	buffer := make([]byte, size)
	status, _, _ := query.Call(handle, 60, uintptr(unsafe.Pointer(&buffer[0])), uintptr(size), uintptr(unsafe.Pointer(&size)))
	if status != 0 {
		return nil, errors.New("Windows could not verify the previous Clips command")
	}
	type unicodeString struct {
		Length, MaximumLength uint16
		Buffer                *uint16
	}
	command := (*unicodeString)(unsafe.Pointer(&buffer[0]))
	if command.Length == 0 || command.Length%2 != 0 || command.Buffer == nil {
		return nil, errors.New("Empty Clips process command")
	}
	// The NT API returns the string within this buffer. Validate before dereferencing.
	base := uintptr(unsafe.Pointer(&buffer[0]))
	ptr := uintptr(unsafe.Pointer(command.Buffer))
	if ptr < base || ptr+uintptr(command.Length) > base+uintptr(len(buffer)) {
		return nil, errors.New("Invalid Clips process command")
	}
	text := syscall.UTF16ToString(unsafe.Slice(command.Buffer, int(command.Length)/2))
	runtime.KeepAlive(buffer)
	var count int32
	line, _ := syscall.UTF16PtrFromString(text)
	argv, err := syscall.CommandLineToArgv(line, &count)
	if err != nil || argv == nil || count < 1 || count > 64 {
		return nil, errors.New("Invalid Clips process arguments")
	}
	defer syscall.LocalFree(syscall.Handle(unsafe.Pointer(argv)))
	args := make([]string, int(count))
	for i := range args {
		args[i] = syscall.UTF16ToString(argv[i][:])
	}
	return args, nil
}

func readWorkerJSON(client *http.Client, base, path string, destination any) error {
	response, err := client.Get(base + path)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return fmt.Errorf("Clips check returned HTTP %d", response.StatusCode)
	}
	return json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(destination)
}

func stopLegacyWorker() error { return stopLegacyWorkerAt(8765) }

func stopLegacyWorkerAt(port int) error {
	client := &http.Client{Timeout: 4 * time.Second}
	base := "http://127.0.0.1:" + strconv.Itoa(port)
	var identity struct {
		Version      string `json:"version"`
		RenderEngine string `json:"render_engine"`
		PostSafety   string `json:"post_safety"`
	}
	if err := readWorkerJSON(client, base, "/api/status", &identity); err != nil {
		return errors.New("Could not check the previous Clips session; try again")
	}
	if !isLegacyClipsVersion(identity.Version) || (identity.RenderEngine != "FFmpeg" && identity.RenderEngine != "FFmpeg required") || identity.PostSafety != "consent per destination" {
		return errors.New("Another service is using the Clips address; it was left running")
	}
	pid, err := listeningWorkerPID(port)
	if err != nil {
		return err
	}
	if pid == 0 {
		return nil
	}
	currentSession, err := processSession(uint32(os.Getpid()))
	if err != nil {
		return errors.New("Could not verify this Windows session")
	}
	oldSession, err := processSession(pid)
	if err != nil || oldSession != currentSession {
		return errors.New("Clips belongs to another Windows session; it was left running")
	}
	handle, _, openErr := restartKernel.NewProc("OpenProcess").Call(0x00100000|0x1000|0x0001, 0, uintptr(pid)) // SYNCHRONIZE, QUERY_LIMITED_INFORMATION, TERMINATE
	if handle == 0 {
		return fmt.Errorf("Windows did not allow access to the previous Clips session: %v", openErr)
	}
	defer restartKernel.NewProc("CloseHandle").Call(handle)
	args, err := processArguments(handle)
	if err != nil {
		return err
	}
	if !isClipsWorkerCommand(args, port) {
		return errors.New("The process on the Clips address is not a recognized VYRA video worker; it was left running")
	}
	var queue []struct {
		Status string `json:"status"`
	}
	if err := readWorkerJSON(client, base, "/api/queue", &queue); err != nil {
		return errors.New("Could not verify publishing status; the previous Clips session was left running")
	}
	for _, post := range queue {
		if post.Status == "sending" || post.Status == "submitting" || post.Status == "publishing" {
			return errors.New("A post is still uploading. Wait for it to finish, then try opening Clips again.")
		}
	}
	owner, err := listeningWorkerPID(port)
	if err != nil {
		return err
	}
	if owner == 0 {
		return nil
	}
	if owner != pid {
		return errors.New("The Clips listener changed; try again")
	}
	ok, _, killErr := restartKernel.NewProc("TerminateProcess").Call(handle, 0)
	if ok == 0 {
		return fmt.Errorf("Windows could not close the previous Clips session: %v", killErr)
	}
	restartKernel.NewProc("WaitForSingleObject").Call(handle, 3000)
	for attempt := 0; attempt < 30; attempt++ {
		owner, err = listeningWorkerPID(port)
		if err != nil {
			return err
		}
		if owner == 0 {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return errors.New("The previous Clips address has not released yet; try again")
}
