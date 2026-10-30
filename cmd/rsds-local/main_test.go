package main

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestOverrideParsing(t *testing.T) {
	for _, input := range []string{"rsds-infra-helm=4", "https://github.com/renf7/rsds-infra-helm/pull/4"} {
		name, n, e := parseOverride(input)
		if e != nil || name != "rsds-infra-helm" || n != 4 {
			t.Fatalf("%s: %s %d %v", input, name, n, e)
		}
	}
	for _, input := range []string{"rsds-infra-helm=-1", "https://evil.example/renf7/rsds-infra-helm/pull/4", "https://github.com/other/rsds-infra-helm/pull/4", "rsds-infra-helm=4;bad", "https://github.com/renf7/rsds-infra-helm/pull/4?x=1"} {
		if _, _, e := parseOverride(input); e == nil {
			t.Fatalf("accepted %s", input)
		}
	}
	o := overrides{}
	if e := o.Set("rsds-infra-helm=4"); e != nil {
		t.Fatal(e)
	}
	if e := o.Set("rsds-infra-helm=5"); e == nil {
		t.Fatal("duplicate accepted")
	}
}
func TestPathSafety(t *testing.T) {
	for _, s := range []string{"../outside", "a/../../outside", "C:/outside", "a\\..\\outside"} {
		if safeRelative(s) {
			t.Fatalf("unsafe path %s", s)
		}
	}
	if !safeRelative("charts/company-page") || !safeRelative(".") {
		t.Fatal("valid path rejected")
	}
	root := t.TempDir()
	if inside(root, filepath.Join(root, "..", "outside")) {
		t.Fatal("outside state accepted")
	}
}
func TestManifestAndUnmanagedState(t *testing.T) {
	root := t.TempDir()
	p := filepath.Join(root, "manifest.json")
	if e := os.WriteFile(p, []byte(`{"chart":{"repository":"rsds-infra-helm","path":"../outside"},"images":[{"repository":"rsds-infra-company-page","context":".","valuesPrefix":"image"}]}`), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e := readManifest(p); e == nil {
		t.Fatal("unsafe manifest accepted")
	}
	if e := os.WriteFile(filepath.Join(root, "state.json"), []byte(`{"owner":"someone-else","cluster":"production"}`), 0600); e != nil {
		t.Fatal(e)
	}
	if e := existing("down", root); e == nil || !strings.Contains(e.Error(), "unmanaged") {
		t.Fatalf("unsafe teardown not rejected: %v", e)
	}
}
func TestExtractOnlyExecutable(t *testing.T) {
	var b bytes.Buffer
	w := zip.NewWriter(&b)
	f, e := w.Create("windows-amd64/helm.exe")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = f.Write([]byte("test-binary")); e != nil {
		t.Fatal(e)
	}
	if e = w.Close(); e != nil {
		t.Fatal(e)
	}
	out, e := extractHelm(b.Bytes(), true)
	if e != nil || string(out) != "test-binary" {
		t.Fatalf("extract: %s %v", out, e)
	}
}

func TestRunRejectsUnapprovedExecutable(t *testing.T) {
	if _, err := run("", nil, "unapproved-command"); err == nil {
		t.Fatal("expected executable allowlist rejection")
	}
}
