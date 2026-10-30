package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestBrowserE2ERequiresExplicitOptIn(t *testing.T) {
	root := t.TempDir()
	s := &State{WorkRoot: root, RunDirectory: root, Status: "VERIFYING"}
	missing := filepath.Join(root, "missing-browser-source")
	if err := verifyBrowserE2E(s, missing); err != nil {
		t.Fatal(err)
	}
	if s.E2E != nil || s.Status != "VERIFYING" {
		t.Fatal("disabled E2E changed validation state")
	}
	if _, err := os.Stat(filepath.Join(root, "e2e")); !os.IsNotExist(err) {
		t.Fatal("disabled E2E created browser artifacts")
	}
	s.E2EEnabled = true
	if err := verifyBrowserE2E(s, missing); err == nil {
		t.Fatal("enabled E2E skipped missing test source")
	}
	data, err := os.ReadFile(filepath.Join(root, "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	var saved State
	if err = json.Unmarshal(data, &saved); err != nil {
		t.Fatal(err)
	}
	if !saved.E2EEnabled || saved.Status != "FAILED_E2E" {
		t.Fatal("enabled E2E failure not recorded")
	}
}

func TestBrowserReportMustProveHeadlessSuccess(t *testing.T) {
	path := filepath.Join(t.TempDir(), "results.json")
	for _, report := range []string{
		`not json`, `{}`, `{"browser":"chromium","headless":true,"tests":6,"passed":true}`, `{"browser":"chromium","headless":true,"tests":0,"passed":true}`,
		`{"browser":"chromium","headless":true,"tests":16,"failures":1,"passed":true}`,
		`{"browser":"chromium","headless":false,"tests":16,"passed":true}`,
		`{"browser":"firefox","headless":true,"tests":16,"passed":true}`,
	} {
		if err := os.WriteFile(path, []byte(report), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := readBrowserResult(path); err == nil {
			t.Fatalf("accepted incomplete report: %s", report)
		}
	}
	if err := os.WriteFile(path, []byte(`{"browser":"chromium","headless":true,"tests":16,"passed":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	if result, err := readBrowserResult(path); err != nil || result.Tests != 16 {
		t.Fatalf("valid report: %v %v", result, err)
	}
	if _, err := readBrowserResult(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("accepted absent report")
	}
}

func TestBrowserImageTracksTestInputs(t *testing.T) {
	root := t.TempDir()
	if _, err := browserImage(root); err == nil {
		t.Fatal("accepted missing E2E source")
	}
	for _, name := range []string{"Dockerfile", "requirements.txt", "test_site.py", "test_auth.py", ".dockerignore"} {
		if err := os.WriteFile(filepath.Join(root, name), []byte(name), 0600); err != nil {
			t.Fatal(err)
		}
	}
	first, err := browserImage(root)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "test_site.py"), []byte("new tests"), 0600); err != nil {
		t.Fatal(err)
	}
	second, err := browserImage(root)
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("changed tests reused image identity")
	}
}
