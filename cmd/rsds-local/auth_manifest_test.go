package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAuthenticationCannotSilentlyUseUnbuiltImages(t *testing.T) {
	path := filepath.Join(t.TempDir(), "manifest.json")
	data := `{"authentication":true,"chart":{"repository":"rsds-infra-helm","path":"charts/company-page"},"images":[{"repository":"rsds-infra-company-page","context":".","valuesPrefix":"image"}],"checks":[{"path":"/","repository":"rsds-infra-company-page","file":"index.html"}]}`
	if err := os.WriteFile(path, []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readManifest(path); err == nil {
		t.Fatal("auth mode accepted missing auth/fixture build provenance")
	}
}
