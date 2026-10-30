package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestManifestSupportsBuiltImageHTMLIntegrity(t *testing.T) {
	for _, tc := range []struct {
		name, check string
		valid       bool
	}{
		{"built HTML", `"imageFile":"usr/share/nginx/html/index.html"`, true},
		{"traversal", `"imageFile":"../etc/passwd"`, false},
		{"ambiguous", `"imageFile":"usr/share/nginx/html/index.html","file":"public/index.html"`, false},
		{"absolute", `"imageFile":"/etc/passwd"`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "manifest.json")
			body := `{"chart":{"repository":"rsds-infra-helm","path":"charts/company-page"},"images":[{"repository":"rsds-infra-company-page","context":".","valuesPrefix":"image"}],"checks":[{"path":"/","repository":"rsds-infra-company-page",` + tc.check + `}]}`
			if err := os.WriteFile(path, []byte(body), 0600); err != nil {
				t.Fatal(err)
			}
			_, err := readManifest(path)
			if (err == nil) != tc.valid {
				t.Fatalf("valid=%v: %v", tc.valid, err)
			}
		})
	}
}
