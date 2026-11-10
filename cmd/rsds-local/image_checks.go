package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// Compare compiled pages with the immutable image built from the selected Git SHA.
// Source assets still use direct checkout hashes. No host directory is mounted.
func expectedHTTPContent(s *State, check Check) (data []byte, err error) {
	source := s.Sources[check.Repository]
	if source == nil {
		return nil, errors.New("missing expected source repository")
	}
	if check.ImageFile == "" {
		return os.ReadFile(filepath.Join(source.Directory, check.File))
	}
	if !safeRelative(check.ImageFile) || check.File != "" || source.ImageID == "" {
		return nil, errors.New("invalid compiled-page image provenance")
	}
	directory, err := os.MkdirTemp(s.RunDirectory, "http-expected-")
	if err != nil {
		return nil, err
	}
	container, err := docker(s, "create", "--entrypoint", "/bin/true", source.ImageID)
	if err != nil {
		return nil, err
	}
	defer func() { _, removeErr := docker(s, "rm", container); err = errors.Join(err, removeErr) }()
	path := filepath.Join(directory, "expected")
	if _, err = docker(s, "cp", fmt.Sprintf("%s:/%s", container, check.ImageFile), path); err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}
