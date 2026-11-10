package main

import (
	"path/filepath"
	"testing"
)

func TestCompiledHTMLRequiresBuiltImageProvenance(t *testing.T) {
	s := &State{RunDirectory: t.TempDir(), Sources: map[string]*Source{}}
	check := Check{Repository: "rsds-infra-company-page", ImageFile: "usr/share/nginx/html/index.html"}
	if _, err := expectedHTTPContent(s, check); err == nil {
		t.Fatal("missing source accepted")
	}
	s.Sources[check.Repository] = &Source{}
	if _, err := expectedHTTPContent(s, check); err == nil {
		t.Fatal("unbuilt image accepted")
	}
	s.Sources[check.Repository].ImageID = "sha256:unavailable"
	check.ImageFile = "../outside"
	if _, err := expectedHTTPContent(s, check); err == nil {
		t.Fatal("image traversal accepted")
	}
	check.ImageFile = "usr/share/nginx/html/index.html"
	s.RunDirectory = filepath.Join(t.TempDir(), "missing")
	if _, err := expectedHTTPContent(s, check); err == nil {
		t.Fatal("missing managed run directory accepted")
	}
}
