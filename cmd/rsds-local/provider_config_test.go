package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPrivateProviderConfig(t *testing.T) {
	path := filepath.Join(t.TempDir(), "providers.env")
	valid := "RSDS_AUTH_PUBLIC_BASE_URL=http://127.0.0.1:18092\nRSDS_AUTH_PROVIDERS_GITHUB_CLIENT_ID=test-app\nRSDS_AUTH_PROVIDERS_GITHUB_CLIENT_SECRET=test-only-value\n"
	for _, value := range []string{valid, valid + "AWS_SECRET_ACCESS_KEY=forbidden\n", valid + "RSDS_AUTH_PUBLIC_BASE_URL=https://duplicate.test\n", strings.Replace(valid, "http://127.0.0.1:18092", "http://remote.test", 1), strings.Replace(valid, "RSDS_AUTH_PROVIDERS_GITHUB_CLIENT_ID=test-app\n", "", 1)} {
		if err := os.WriteFile(path, []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
		err := validateProviderFile(path)
		if (value == valid) != (err == nil) {
			t.Fatalf("unexpected validation result: %v", err)
		}
		if err != nil && strings.Contains(err.Error(), "test-only-value") {
			t.Fatal("secret exposed")
		}
	}
}
func TestLiveProviderE2ERejectedBeforeTools(t *testing.T) {
	err := up("../../local-test-auth.json", t.TempDir(), "default", "rsds-local-test", 18092, nil, true, "not-read.env")
	if err == nil || !strings.Contains(err.Error(), "forbids automated") {
		t.Fatalf("expected live E2E rejection, got %v", err)
	}
}
