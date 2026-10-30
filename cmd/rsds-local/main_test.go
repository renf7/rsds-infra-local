package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
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

func TestCLIValidation(t *testing.T) {
	if err := entry(nil); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"unknown"}, {"up", "--unknown"}, {"up", "extra"}, {"up"},
		{"up", "--docker-context", "default", "--port", "80"},
		{"up", "--docker-context", "default", "--cluster", "production"},
		{"status", "--workdir", t.TempDir()},
	} {
		if err := entry(args); err == nil {
			t.Fatalf("accepted %v", args)
		}
	}
	o := overrides{}
	if err := o.Set("bad"); err == nil {
		t.Fatal("accepted malformed override")
	}
	if o.String() == "" {
		t.Fatal("missing flag representation")
	}
}

func TestManifestValidation(t *testing.T) {
	valid := Manifest{Chart: Chart{"rsds-infra-helm", "charts/company-page"}, Images: []Image{{"rsds-infra-company-page", ".", "image"}}, Checks: []Check{{"/", "rsds-infra-company-page", "public/index.html"}}}
	for _, mode := range []string{"valid", "image", "prefix", "check", "empty"} {
		m := valid
		m.Images = append([]Image(nil), valid.Images...)
		m.Checks = append([]Check(nil), valid.Checks...)
		switch mode {
		case "image":
			m.Images[0].Context = "../escape"
		case "prefix":
			m.Images = append(m.Images, m.Images[0])
		case "check":
			m.Checks[0].Repository = "unknown"
		case "empty":
			m.Checks = nil
		}
		b, err := json.Marshal(m)
		if err != nil {
			t.Fatal(err)
		}
		p := filepath.Join(t.TempDir(), "manifest.json")
		if err = os.WriteFile(p, b, 0600); err != nil {
			t.Fatal(err)
		}
		_, err = readManifest(p)
		if (err == nil) != (mode == "valid") {
			t.Fatalf("%s: %v", mode, err)
		}
	}
	p := filepath.Join(t.TempDir(), "missing")
	if _, err := readManifest(p); err == nil {
		t.Fatal("missing file accepted")
	}
	if err := os.WriteFile(p, []byte(`{"unknown":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readManifest(p); err == nil {
		t.Fatal("unknown field accepted")
	}
}

func TestHTTPSourceIntegrityAndDownloadLimits(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/missing" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte("actual"))
	}))
	defer server.Close()
	if b, err := fetch(server.URL, 10); err != nil || string(b) != "actual" {
		t.Fatalf("download: %q %v", b, err)
	}
	if _, err := fetch(server.URL, 2); err == nil {
		t.Fatal("oversized download accepted")
	}
	if _, err := fetch(server.URL+"/missing", 10); err == nil {
		t.Fatal("HTTP failure accepted")
	}
	if _, err := fetch(":invalid", 10); err == nil {
		t.Fatal("invalid URL accepted")
	}
	root := t.TempDir()
	s := &State{URL: server.URL, Sources: map[string]*Source{"rsds-infra-company-page": {Directory: root}}}
	c := Check{"/", "rsds-infra-company-page", "index.html"}
	if _, err := checkHTTP(s, c); err == nil {
		t.Fatal("missing expected source accepted")
	}
	if err := os.WriteFile(filepath.Join(root, c.File), []byte("different"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := checkHTTP(s, c); err == nil {
		t.Fatal("source mismatch accepted")
	}
	if err := os.WriteFile(filepath.Join(root, c.File), []byte("actual"), 0600); err != nil {
		t.Fatal(err)
	}
	if result, err := checkHTTP(s, c); err != nil || !result.SourceMatches {
		t.Fatalf("check: %v %v", result, err)
	}
}

func TestArchiveValidation(t *testing.T) {
	for _, zipFormat := range []bool{true, false} {
		if _, err := extractHelm([]byte("invalid"), zipFormat); err == nil {
			t.Fatal("invalid archive accepted")
		}
	}
	for _, name := range []string{"linux-amd64/helm", "unrelated"} {
		var b bytes.Buffer
		gz := gzip.NewWriter(&b)
		tw := tar.NewWriter(gz)
		if err := tw.WriteHeader(&tar.Header{Name: name, Size: 6, Mode: 0700, Typeflag: tar.TypeReg}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write([]byte("binary")); err != nil {
			t.Fatal(err)
		}
		if err := tw.Close(); err != nil {
			t.Fatal(err)
		}
		if err := gz.Close(); err != nil {
			t.Fatal(err)
		}
		out, err := extractHelm(b.Bytes(), false)
		if name == "unrelated" {
			if err == nil {
				t.Fatal("missing executable accepted")
			}
		} else if err != nil || string(out) != "binary" {
			t.Fatalf("tar extract: %q %v", out, err)
		}
	}
}

func TestManagedStateAndCachedTool(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "state.json"), []byte("not json"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := existing("down", root); err == nil {
		t.Fatal("corrupt state accepted")
	}
	s := &State{Owner: owner, WorkRoot: root, RunDirectory: filepath.Join(root, "runs", "rsds-local-test"), Cluster: "rsds-local-test", Kubeconfig: filepath.Join(root, "kubeconfig"), Status: "PREPARING"}
	if err := os.MkdirAll(s.RunDirectory, 0700); err != nil {
		t.Fatal(err)
	}
	if err := save(s); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "state.json")); err != nil {
		t.Fatal(err)
	}
	s.WorkRoot = filepath.Join(root, "missing")
	if err := save(s); err == nil {
		t.Fatal("missing state directory accepted")
	}
	// A cached tool avoids network access and requires no global installation.
	t.Setenv("PATH", t.TempDir())
	if err := os.Mkdir(filepath.Join(root, "bin"), 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "bin", "kind")
	if runtime.GOOS == "windows" {
		path += ".exe"
	}
	if err := os.WriteFile(path, []byte("cached"), 0700); err != nil {
		t.Fatal(err)
	}
	if got, err := ensureTool(root, "kind"); err != nil || got != path {
		t.Fatalf("cached tool %s %v", got, err)
	}
}

func TestStartupRejectsUnknownSourcesAndMissingTools(t *testing.T) {
	manifest, err := filepath.Abs("../../local-test.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := up(manifest, t.TempDir(), "default", "rsds-local-test", 18080, overrides{"rsds-infra-unknown": 1}); err == nil || !strings.Contains(err.Error(), "not in the manifest") {
		t.Fatalf("unknown source: %v", err)
	}
	t.Setenv("PATH", t.TempDir())
	if err := up(manifest, t.TempDir(), "default", "rsds-local-test", 18080, nil); err == nil || !strings.Contains(err.Error(), "install docker") {
		t.Fatalf("missing prerequisite: %v", err)
	}
	if _, err := run("", nil, "git", "--version"); err == nil {
		t.Fatal("missing executable accepted")
	}
	root := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(root, []byte("file"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := ensureTool(root, "kind"); err == nil {
		t.Fatal("invalid tool cache accepted")
	}
}

func TestHTTPReadinessRetry(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if requests.Add(1) == 1 {
			http.Error(w, "starting", 503)
			return
		}
		_, _ = w.Write([]byte("ready"))
	}))
	defer server.Close()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "index.html"), []byte("ready"), 0600); err != nil {
		t.Fatal(err)
	}
	s := &State{URL: server.URL, Sources: map[string]*Source{"rsds-infra-company-page": {Directory: root}}}
	if _, err := checkHTTP(s, Check{"/", "rsds-infra-company-page", "index.html"}); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 2 {
		t.Fatalf("expected readiness retry: %d", requests.Load())
	}
}

func TestArchiveMissingExecutableAndCorruptTar(t *testing.T) {
	var b bytes.Buffer
	zw := zip.NewWriter(&b)
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := extractHelm(b.Bytes(), true); err == nil {
		t.Fatal("empty archive accepted")
	}
	b.Reset()
	gz := gzip.NewWriter(&b)
	if _, err := gz.Write(bytes.Repeat([]byte("invalid"), 100)); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := extractHelm(b.Bytes(), false); err == nil {
		t.Fatal("corrupt tar accepted")
	}
}
