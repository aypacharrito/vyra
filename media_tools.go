package main

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

const mediaVersion = "9.0.2"
const mediaArchiveURL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip"
const mediaArchiveSHA = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"

func mediaRoot() string { root, _ := os.UserCacheDir(); return filepath.Join(root, "VYRA", "Media") }
func mediaBin() string  { return filepath.Join(mediaRoot(), "ffmpeg-"+mediaVersion, "bin") }
func mediaPaths() (string, string, bool) {
	suffix := ""
	if runtime.GOOS == "windows" {
		suffix = ".exe"
	}
	ffmpeg, ffprobe := filepath.Join(mediaBin(), "ffmpeg"+suffix), filepath.Join(mediaBin(), "ffprobe"+suffix)
	if a, e := os.Stat(ffmpeg); e == nil && !a.IsDir() {
		if b, e := os.Stat(ffprobe); e == nil && !b.IsDir() {
			return ffmpeg, ffprobe, true
		}
	}
	ffmpeg, e := exec.LookPath("ffmpeg")
	if e != nil {
		return "", "", false
	}
	ffprobe, e = exec.LookPath("ffprobe")
	return ffmpeg, ffprobe, e == nil
}
func verifyMedia(ctx context.Context, ffmpeg, ffprobe string) error {
	for _, program := range []string{ffmpeg, ffprobe} {
		cmd := exec.CommandContext(ctx, program, "-version")
		hideWorker(cmd)
		if err := cmd.Run(); err != nil {
			return errors.New("The video engine could not start. Choose Repair video tools and try again.")
		}
	}
	cmd := exec.CommandContext(ctx, ffmpeg, "-hide_banner", "-filters")
	hideWorker(cmd)
	filters, err := cmd.Output()
	if err != nil || !strings.Contains(string(filters), "subtitles") {
		return errors.New("This video engine cannot render captions.")
	}
	cmd = exec.CommandContext(ctx, ffmpeg, "-hide_banner", "-encoders")
	hideWorker(cmd)
	encoders, err := cmd.Output()
	if err != nil || !strings.Contains(string(encoders), "libx264") {
		return errors.New("This video engine cannot encode the required MP4 format.")
	}
	return nil
}
func fileSHA(filename string) (string, error) {
	f, e := os.Open(filename)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	_, e = io.Copy(h, f)
	return hex.EncodeToString(h.Sum(nil)), e
}
func extractMediaArchive(filename, destination string) error {
	archive, err := zip.OpenReader(filename)
	if err != nil {
		return err
	}
	defer archive.Close()
	if err = os.MkdirAll(destination, 0700); err != nil {
		return err
	}
	found := map[string]bool{}
	var total uint64
	for _, entry := range archive.File {
		name := strings.ReplaceAll(entry.Name, "\\", "/")
		clean := path.Clean(name)
		if path.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, "../") || strings.Contains(clean, ":") || entry.Mode()&os.ModeSymlink != 0 {
			return errors.New("Unexpected video engine archive path")
		}
		target := ""
		switch {
		case strings.HasSuffix(clean, "/bin/ffmpeg.exe"):
			target = "bin/ffmpeg.exe"
		case strings.HasSuffix(clean, "/bin/ffprobe.exe"):
			target = "bin/ffprobe.exe"
		case path.Base(clean) == "LICENSE":
			target = "LICENSE"
		case path.Base(clean) == "README.txt":
			target = "README.txt"
		}
		if target == "" {
			continue
		}
		if found[target] {
			return errors.New("Duplicate video engine archive entry")
		}
		found[target] = true
		total += entry.UncompressedSize64
		if entry.UncompressedSize64 > 300<<20 || total > 600<<20 {
			return errors.New("Video engine archive exceeds expected size")
		}
		output := filepath.Join(destination, filepath.FromSlash(target))
		if err = os.MkdirAll(filepath.Dir(output), 0700); err != nil {
			return err
		}
		input, e := entry.Open()
		if e != nil {
			return e
		}
		out, e := os.OpenFile(output, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0700)
		if e != nil {
			input.Close()
			return e
		}
		_, copyErr := io.Copy(out, io.LimitReader(input, 300<<20))
		input.Close()
		closeErr := out.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	if !found["bin/ffmpeg.exe"] || !found["bin/ffprobe.exe"] {
		return errors.New("The download is missing a video engine component")
	}
	return os.WriteFile(filepath.Join(destination, "BUILD_SOURCE.txt"), []byte("FFmpeg "+mediaVersion+" essentials build by Gyan Doshi\n"+mediaArchiveURL+"\nSHA256: "+mediaArchiveSHA+"\nSource: https://github.com/FFmpeg/FFmpeg/commit/946fcce07b\nBuild information: https://www.gyan.dev/ffmpeg/builds/\n"), 0600)
}
func ensureMediaTools(ctx context.Context, report func(string)) error {
	if ffmpeg, ffprobe, ok := mediaPaths(); ok {
		if verifyMedia(ctx, ffmpeg, ffprobe) == nil {
			return nil
		}
	}
	if runtime.GOOS != "windows" {
		return errors.New("Install FFmpeg and FFprobe using your system package manager.")
	}
	root := mediaRoot()
	if err := os.MkdirAll(root, 0700); err != nil {
		return err
	}
	archive := filepath.Join(root, "ffmpeg-"+mediaVersion+".zip")
	digest, _ := fileSHA(archive)
	if digest != mediaArchiveSHA {
		report("Downloading the video engine (about 109 MB)…")
		request, err := http.NewRequestWithContext(ctx, "GET", mediaArchiveURL, nil)
		if err != nil {
			return err
		}
		client := http.Client{Timeout: 8 * time.Minute, CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if req.URL.Scheme != "https" || len(via) > 5 {
				return errors.New("Unexpected video tools redirect")
			}
			return nil
		}}
		response, err := client.Do(request)
		if err != nil {
			return errors.New("Could not download the video engine. Check your internet connection and try again.")
		}
		defer response.Body.Close()
		if response.StatusCode != 200 {
			return fmt.Errorf("Video engine download returned HTTP %d. Try again later.", response.StatusCode)
		}
		temp, err := os.CreateTemp(root, "download-*.zip")
		if err != nil {
			return err
		}
		tempName := temp.Name()
		defer os.Remove(tempName)
		h := sha256.New()
		n, copyErr := io.Copy(io.MultiWriter(temp, h), io.LimitReader(response.Body, (200<<20)+1))
		closeErr := temp.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
		if n > 200<<20 || hex.EncodeToString(h.Sum(nil)) != mediaArchiveSHA {
			return errors.New("Video engine download failed its integrity check. Try again.")
		}
		_ = os.Remove(archive)
		if err = os.Rename(tempName, archive); err != nil {
			return err
		}
	}
	report("Installing and checking the video engine…")
	stage, err := os.MkdirTemp(root, "install-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(stage)
	if err = extractMediaArchive(archive, stage); err != nil {
		return err
	}
	if err = verifyMedia(ctx, filepath.Join(stage, "bin", "ffmpeg.exe"), filepath.Join(stage, "bin", "ffprobe.exe")); err != nil {
		return err
	}
	target := filepath.Dir(mediaBin())
	if _, err = os.Stat(target); err == nil {
		if err = os.Rename(target, target+"-previous-"+token()[:8]); err != nil {
			return err
		}
	}
	return os.Rename(stage, target)
}
func startMediaSetup() {
	videoSetup.Lock()
	if videoSetup.status.State == "running" {
		videoSetup.Unlock()
		return
	}
	videoSetup.status = clipsSetupStatus{"running", "Preparing the video engine…"}
	videoSetup.Unlock()
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
		defer cancel()
		err := ensureMediaTools(ctx, func(detail string) { setupReport("running", detail) })
		if err != nil {
			setupReport("failed", err.Error())
			return
		}
		setupReport("ready", "Video engine ready. Opening your studio…")
	}()
}
