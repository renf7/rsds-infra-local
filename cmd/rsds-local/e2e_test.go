package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestBrowserReportMustProveHeadlessSuccess(t *testing.T) {
	path := filepath.Join(t.TempDir(), "results.json")
	for _, report := range []string{
		`not json`, `{}`, `{"browser":"chromium","headless":true,"tests":0,"passed":true}`,
		`{"browser":"chromium","headless":true,"tests":6,"failures":1,"passed":true}`,
		`{"browser":"chromium","headless":false,"tests":6,"passed":true}`,
		`{"browser":"firefox","headless":true,"tests":6,"passed":true}`,
	} {
		if err := os.WriteFile(path, []byte(report), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := readBrowserResult(path); err == nil {
			t.Fatalf("accepted incomplete report: %s", report)
		}
	}
	if err := os.WriteFile(path, []byte(`{"browser":"chromium","headless":true,"tests":6,"passed":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	if result, err := readBrowserResult(path); err != nil || result.Tests != 6 {
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
	for _, name := range []string{"Dockerfile", "requirements.txt", "test_site.py", ".dockerignore"} {
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
