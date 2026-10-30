package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

type BrowserResult struct {
	Browser  string `json:"browser"`
	Headless bool   `json:"headless"`
	Tests    int    `json:"tests"`
	Failures int    `json:"failures"`
	Errors   int    `json:"errors"`
	Passed   bool   `json:"passed"`
}

func browserImage(context string) (string, error) {
	hash := sha256.New()
	for _, name := range []string{"Dockerfile", "requirements.txt", "test_site.py", ".dockerignore"} {
		data, err := os.ReadFile(filepath.Join(context, name))
		if err != nil {
			return "", err
		}
		hash.Write([]byte(name))
		hash.Write(data)
	}
	return "rsds-local/e2e:" + hex.EncodeToString(hash.Sum(nil))[:12], nil
}

func readBrowserResult(path string) (*BrowserResult, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var result BrowserResult
	if err = json.Unmarshal(data, &result); err != nil {
		return nil, err
	}
	if !result.Passed || !result.Headless || result.Browser != "chromium" || result.Tests < 6 || result.Errors != 0 || result.Failures != 0 {
		return &result, errors.New("headless E2E suite failed or returned incomplete results")
	}
	return &result, nil
}

func runBrowserE2E(s *State, context string) (err error) {
	image, err := browserImage(context)
	if err != nil {
		return err
	}
	if _, err = docker(s, "build", "--pull", "-t", image, context); err != nil {
		return err
	}
	directory := filepath.Join(s.RunDirectory, "e2e")
	if err = os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	// No host credentials/volumes or Docker socket are exposed to the browser.
	// Join only the local kind network and reach this cluster's NodePort directly.
	container := s.Cluster + "-e2e"
	// Create separately so an existing container is never removed on a name conflict.
	if _, err = docker(s, "create", "--name", container, "--network", "kind", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--shm-size", "256m", "--env", "BASE_URL=http://"+s.Cluster+"-control-plane:30080", image); err != nil {
		return err
	}
	defer func() {
		if _, cleanupErr := docker(s, "rm", "-f", container); cleanupErr != nil {
			err = errors.Join(err, cleanupErr)
		}
	}()
	output, startErr := docker(s, "start", "--attach", container)
	logErr := os.WriteFile(filepath.Join(directory, "browser.log"), []byte(output), 0600)
	_, copyErr := docker(s, "cp", container+":/artifacts/.", directory)
	// docker start --attach does not guarantee propagation of the container's exit code.
	code, inspectErr := docker(s, "inspect", "--format", "{{.State.ExitCode}}", container)
	result, reportErr := readBrowserResult(filepath.Join(directory, "results.json"))
	s.E2E = result
	if err = errors.Join(startErr, logErr, copyErr, inspectErr, reportErr); err != nil {
		return err
	}
	if code != "0" {
		return fmt.Errorf("headless E2E exited with code %s; inspect %s", code, directory)
	}
	fmt.Printf("Headless Chromium: %d tests passed; artifacts: %s\n", result.Tests, directory)
	return nil
}
