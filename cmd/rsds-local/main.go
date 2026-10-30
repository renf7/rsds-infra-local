package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

const owner = "renf7/rsds-infra-local"
const kindVersion = "v0.33.0"
const helmVersion = "v4.3.1"
const nodeImage = "kindest/node:v1.34.0"

var repoPattern = regexp.MustCompile(`^rsds-infra-[a-z0-9][a-z0-9-]*$`)
var valuePattern = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)*$`)
var clusterPattern = regexp.MustCompile(`^rsds-local-[a-z0-9-]{1,40}$`)

type Chart struct {
	Repository string `json:"repository"`
	Path       string `json:"path"`
}
type Image struct {
	Repository   string `json:"repository"`
	Context      string `json:"context"`
	ValuesPrefix string `json:"valuesPrefix"`
}
type Check struct {
	Path       string `json:"path"`
	Repository string `json:"repository"`
	File       string `json:"file"`
}
type Manifest struct {
	Chart  Chart   `json:"chart"`
	Images []Image `json:"images"`
	Checks []Check `json:"checks"`
}
type Source struct {
	Repository string `json:"repository"`
	Branch     string `json:"branch,omitempty"`
	PR         int    `json:"pr,omitempty"`
	Commit     string `json:"commit"`
	Directory  string `json:"directory"`
	Image      string `json:"image,omitempty"`
	ImageID    string `json:"imageID,omitempty"`
}
type Result struct {
	Path          string `json:"path"`
	Status        int    `json:"status"`
	Hash          string `json:"sha256"`
	SourceMatches bool   `json:"sourceMatches"`
}
type State struct {
	Owner         string             `json:"owner"`
	Cluster       string             `json:"cluster"`
	DockerContext string             `json:"dockerContext"`
	Kubeconfig    string             `json:"kubeconfig"`
	WorkRoot      string             `json:"workRoot"`
	RunDirectory  string             `json:"runDirectory"`
	URL           string             `json:"url"`
	Sources       map[string]*Source `json:"sources"`
	Results       []Result           `json:"results,omitempty"`
	Status        string             `json:"status"`
	Created       string             `json:"created"`
}
type overrides map[string]int

func (o overrides) String() string { return fmt.Sprint(map[string]int(o)) }
func (o overrides) Set(s string) error {
	name, number, err := parseOverride(s)
	if err != nil {
		return err
	}
	if _, ok := o[name]; ok {
		return fmt.Errorf("duplicate PR override for %s", name)
	}
	o[name] = number
	return nil
}
func parseOverride(s string) (string, int, error) {
	var name, number string
	if strings.HasPrefix(s, "https://") {
		u, e := url.Parse(s)
		if e != nil || u.Host != "github.com" || u.RawQuery != "" || u.Fragment != "" {
			return "", 0, errors.New("expected a github.com/renf7 repository PR URL")
		}
		parts := strings.Split(strings.Trim(u.Path, "/"), "/")
		if len(parts) != 4 || parts[0] != "renf7" || parts[2] != "pull" {
			return "", 0, errors.New("invalid PR URL")
		}
		name, number = parts[1], parts[3]
	} else {
		parts := strings.Split(s, "=")
		if len(parts) != 2 {
			return "", 0, errors.New("use --pr repository=number or --pr https://github.com/renf7/repository/pull/number")
		}
		name, number = parts[0], parts[1]
	}
	n, e := strconv.Atoi(number)
	if e != nil || n < 1 || !repoPattern.MatchString(name) {
		return "", 0, errors.New("invalid repository or PR number")
	}
	return name, n, nil
}
func main() {
	if err := entry(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "ERROR:", err)
		os.Exit(1)
	}
}
func entry(args []string) error {
	if len(args) == 0 {
		usage()
		return nil
	}
	command := args[0]
	if command != "up" && command != "down" && command != "status" {
		usage()
		return fmt.Errorf("unknown command %q", command)
	}
	fs := flag.NewFlagSet(command, flag.ContinueOnError)
	manifestPath := fs.String("manifest", "local-test.json", "repository/image manifest")
	work := fs.String("workdir", "", "managed directory (default: manifest directory/.local)")
	dockerContext := fs.String("docker-context", "", "local Docker context (required for up)")
	cluster := fs.String("cluster", "", "unique rsds-local-* cluster name")
	port := fs.Int("port", 18080, "loopback HTTP port")
	prs := overrides{}
	fs.Var(prs, "pr", "repeatable repository=PR or GitHub PR URL")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("unexpected positional arguments")
	}
	manifestAbs, err := filepath.Abs(*manifestPath)
	if err != nil {
		return err
	}
	root := *work
	if root == "" {
		root = filepath.Join(filepath.Dir(manifestAbs), ".local")
	}
	root, err = filepath.Abs(root)
	if err != nil {
		return err
	}
	if command != "up" {
		return existing(command, root)
	}
	if *dockerContext == "" {
		return errors.New("choose your local context explicitly: --docker-context desktop-linux (Windows) or --docker-context default (local Linux)")
	}
	if *port < 1024 || *port > 65535 {
		return errors.New("port must be between 1024 and 65535")
	}
	if *cluster == "" {
		*cluster = "rsds-local-" + time.Now().Format("20060102-150405")
	}
	if !clusterPattern.MatchString(*cluster) {
		return errors.New("cluster name must start rsds-local- and contain only lowercase letters, digits and hyphens")
	}
	return up(manifestAbs, root, *dockerContext, *cluster, *port, prs)
}
func usage() {
	fmt.Println("rsds-local up --docker-context desktop-linux [--pr rsds-infra-helm=4] [--pr rsds-infra-company-page=9] [--port 18080]\nrsds-local status\nrsds-local down\nWithout --pr, every source/image is built from its repository's actual default branch. Run from the repository root.")
}
func readManifest(path string) (Manifest, error) {
	var m Manifest
	f, e := os.Open(path)
	if e != nil {
		return m, e
	}
	defer f.Close()
	d := json.NewDecoder(io.LimitReader(f, 1<<20))
	d.DisallowUnknownFields()
	if e = d.Decode(&m); e != nil {
		return m, e
	}
	if !repoPattern.MatchString(m.Chart.Repository) || !safeRelative(m.Chart.Path) || len(m.Images) == 0 {
		return m, errors.New("invalid chart or empty image manifest")
	}
	names := map[string]bool{m.Chart.Repository: true}
	prefixes := map[string]bool{}
	for _, im := range m.Images {
		if !repoPattern.MatchString(im.Repository) || !safeRelative(im.Context) || !valuePattern.MatchString(im.ValuesPrefix) || prefixes[im.ValuesPrefix] {
			return m, errors.New("invalid image entry")
		}
		prefixes[im.ValuesPrefix] = true
		names[im.Repository] = true
	}
	for _, c := range m.Checks {
		if !strings.HasPrefix(c.Path, "/") || !names[c.Repository] || !safeRelative(c.File) {
			return m, errors.New("invalid HTTP/source check")
		}
	}
	if len(m.Checks) == 0 {
		return m, errors.New("at least one HTTP check is required")
	}
	return m, nil
}
func safeRelative(p string) bool {
	if p == "" || filepath.IsAbs(p) || strings.Contains(p, ":") {
		return false
	}
	for _, part := range strings.Split(strings.ReplaceAll(p, "\\", "/"), "/") {
		if part == ".." {
			return false
		}
	}
	return true
}
func run(dir string, env []string, command string, args ...string) (string, error) {
	name := strings.TrimSuffix(filepath.Base(command), ".exe")
	switch name {
	case "git", "docker", "kubectl", "kind", "helm":
	default:
		return "", errors.New("executable is not an approved local testing tool")
	}
	fmt.Println("+", filepath.Base(command), strings.Join(args, " "))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	// Approved tools only, resolved from the user's PATH or checksum-verified downloads.
	// Arguments remain separate; no shell interprets repository names or PR input.
	// nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command
	cmd := exec.CommandContext(ctx, command, args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), env...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return string(out), fmt.Errorf("%s failed: %w\n%s", filepath.Base(command), err, out)
	}
	return strings.TrimSpace(string(out)), nil
}
func docker(s *State, args ...string) (string, error) {
	return run("", nil, "docker", append([]string{"--context", s.DockerContext}, args...)...)
}
func kindEnv(s *State) []string {
	return []string{"DOCKER_CONTEXT=" + s.DockerContext, "KUBECONFIG=" + s.Kubeconfig}
}
func kubectl(s *State, args ...string) (string, error) {
	return run("", nil, "kubectl", append([]string{"--kubeconfig", s.Kubeconfig, "--context", "kind-" + s.Cluster, "-n", "rsds-local-test"}, args...)...)
}
func save(s *State) error {
	b, e := json.MarshalIndent(s, "", "  ")
	if e != nil {
		return e
	}
	if e = os.WriteFile(filepath.Join(s.RunDirectory, "report.json"), b, 0600); e != nil {
		return e
	}
	return os.WriteFile(filepath.Join(s.WorkRoot, "state.json"), b, 0600)
}
func localDocker(s *State) error {
	out, e := run("", nil, "docker", "context", "inspect", s.DockerContext, "--format", "{{.Endpoints.docker.Host}}")
	if e != nil {
		return e
	}
	if !(strings.HasPrefix(out, "npipe://") || strings.HasPrefix(out, "unix://")) {
		return errors.New("refusing a remote Docker endpoint; use a local named-pipe or Unix-socket context")
	}
	_, e = docker(s, "info", "--format", "{{.ServerVersion}}")
	return e
}
func up(path, root, dcontext, cluster string, port int, prs overrides) error {
	m, e := readManifest(path)
	if e != nil {
		return e
	}
	names := map[string]bool{m.Chart.Repository: true}
	for _, im := range m.Images {
		names[im.Repository] = true
	}
	for name := range prs {
		if !names[name] {
			return fmt.Errorf("PR override %s is not in the manifest", name)
		}
	}
	for _, tool := range []string{"docker", "git", "kubectl"} {
		if _, e = exec.LookPath(tool); e != nil {
			return fmt.Errorf("install %s first: %w", tool, e)
		}
	}
	if _, e = os.Stat(filepath.Join(root, "state.json")); e == nil {
		return errors.New("a managed run already exists in this workdir; use status/down first or a different --workdir")
	}
	listener, e := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if e != nil {
		return fmt.Errorf("local port unavailable: %w", e)
	}
	listener.Close()
	if e = os.MkdirAll(root, 0700); e != nil {
		return e
	}
	s := &State{Owner: owner, Cluster: cluster, DockerContext: dcontext, WorkRoot: root, RunDirectory: filepath.Join(root, "runs", cluster), URL: fmt.Sprintf("http://127.0.0.1:%d", port), Sources: map[string]*Source{}, Status: "PREPARING", Created: time.Now().UTC().Format(time.RFC3339)}
	if e = os.MkdirAll(s.RunDirectory, 0700); e != nil {
		return e
	}
	s.Kubeconfig = filepath.Join(s.RunDirectory, "kubeconfig")
	if e = localDocker(s); e != nil {
		return e
	}
	kind, e := ensureTool(root, "kind")
	if e != nil {
		return e
	}
	helm, e := ensureTool(root, "helm")
	if e != nil {
		return e
	}
	clusters, e := run("", kindEnv(s), kind, "get", "clusters")
	if e != nil {
		return e
	}
	for _, name := range strings.Fields(clusters) {
		if name == cluster {
			return errors.New("refusing to reuse an existing cluster")
		}
	}
	if e = save(s); e != nil {
		return e
	}
	selected := make([]string, 0, len(names))
	for n := range names {
		selected = append(selected, n)
	}
	sort.Strings(selected)
	for _, name := range selected {
		dir := filepath.Join(s.RunDirectory, name)
		if _, e = run("", nil, "git", "clone", "--depth", "1", "https://github.com/renf7/"+name+".git", dir); e != nil {
			return e
		}
		git := func(args ...string) (string, error) {
			return run(dir, nil, "git", append([]string{"-c", "safe.directory=" + dir}, args...)...)
		}
		branch, e := git("branch", "--show-current")
		if e != nil {
			return e
		}
		if n := prs[name]; n != 0 {
			if _, e = git("fetch", "--depth", "1", "origin", fmt.Sprintf("refs/pull/%d/head", n)); e != nil {
				return e
			}
			if _, e = git("checkout", "--detach", "FETCH_HEAD"); e != nil {
				return e
			}
		}
		commit, e := git("rev-parse", "HEAD")
		if e != nil {
			return e
		}
		source := &Source{Repository: name, Commit: commit, Directory: dir, PR: prs[name]}
		if source.PR == 0 {
			source.Branch = branch
		}
		s.Sources[name] = source
	}
	for _, im := range m.Images {
		source := s.Sources[im.Repository]
		source.Image = "rsds-local/" + im.Repository + ":" + source.Commit[:12]
		if _, e = docker(s, "build", "--pull", "-t", source.Image, filepath.Join(source.Directory, im.Context)); e != nil {
			return e
		}
		source.ImageID, e = docker(s, "image", "inspect", "--format", "{{.Id}}", source.Image)
		if e != nil {
			return e
		}
	}
	s.Status = "CREATING_CLUSTER"
	if e = save(s); e != nil {
		return e
	}
	config := fmt.Sprintf("kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nnodes:\n- role: control-plane\n  extraPortMappings:\n  - containerPort: 30080\n    hostPort: %d\n    listenAddress: 127.0.0.1\n    protocol: TCP\n", port)
	configPath := filepath.Join(s.RunDirectory, "kind.yaml")
	if e = os.WriteFile(configPath, []byte(config), 0600); e != nil {
		return e
	}
	if _, e = run("", kindEnv(s), kind, "create", "cluster", "--name", cluster, "--image", nodeImage, "--config", configPath, "--kubeconfig", s.Kubeconfig, "--wait", "120s", "--retain"); e != nil {
		return fmt.Errorf("%w\nRun down with this workdir to remove the retained test cluster", e)
	}
	for _, im := range m.Images {
		if _, e = run("", kindEnv(s), kind, "load", "docker-image", s.Sources[im.Repository].Image, "--name", cluster); e != nil {
			return e
		}
	}
	chart := filepath.Join(s.Sources[m.Chart.Repository].Directory, m.Chart.Path)
	helmArgs := []string{"upgrade", "--install", "rsds-local", chart, "--kubeconfig", s.Kubeconfig, "--kube-context", "kind-" + cluster, "--namespace", "rsds-local-test", "--create-namespace", "--set", "ingress.enabled=false", "--set", "fullnameOverride=rsds-local", "--set", "service.type=NodePort", "--wait", "--timeout", "120s"}
	for _, im := range m.Images {
		tag := s.Sources[im.Repository].Commit[:12]
		helmArgs = append(helmArgs, "--set", im.ValuesPrefix+".repository=rsds-local/"+im.Repository, "--set", im.ValuesPrefix+".tag="+tag, "--set", im.ValuesPrefix+".pullPolicy=Never")
	}
	if _, e = run("", nil, helm, helmArgs...); e != nil {
		return e
	}
	patch := `[{"op":"add","path":"/spec/ports/0/nodePort","value":30080}]`
	if _, e = kubectl(s, "patch", "service", "rsds-local", "--type=json", "-p", patch); e != nil {
		return e
	}
	s.Status = "VERIFYING"
	if e = save(s); e != nil {
		return e
	}
	for _, check := range m.Checks {
		result, e := checkHTTP(s, check)
		if e != nil {
			return e
		}
		s.Results = append(s.Results, result)
	}
	pods, e := kubectl(s, "get", "pods", "-l", "app.kubernetes.io/instance=rsds-local", "-o", "json")
	if e != nil {
		return e
	}
	if e = os.WriteFile(filepath.Join(s.RunDirectory, "pods.json"), []byte(pods), 0600); e != nil {
		return e
	}
	s.Status = "PASS"
	if e = save(s); e != nil {
		return e
	}
	fmt.Println("PASS:", s.URL, "report:", filepath.Join(s.RunDirectory, "report.json"))
	return nil
}
func checkHTTP(s *State, c Check) (Result, error) {
	client := &http.Client{Timeout: 3 * time.Second}
	deadline := time.Now().Add(90 * time.Second)
	for {
		response, e := client.Get(s.URL + c.Path)
		if e == nil {
			body, readErr := io.ReadAll(io.LimitReader(response.Body, 20<<20))
			response.Body.Close()
			if readErr == nil && response.StatusCode == 200 {
				expected, e := os.ReadFile(filepath.Join(s.Sources[c.Repository].Directory, c.File))
				if e != nil {
					return Result{}, e
				}
				actualHash := sha256.Sum256(body)
				expectedHash := sha256.Sum256(expected)
				if actualHash != expectedHash {
					return Result{}, fmt.Errorf("served bytes for %s do not match selected source", c.Path)
				}
				return Result{Path: c.Path, Status: 200, Hash: hex.EncodeToString(actualHash[:]), SourceMatches: true}, nil
			}
		}
		if time.Now().After(deadline) {
			return Result{}, fmt.Errorf("HTTP check timed out: %s", c.Path)
		}
		time.Sleep(time.Second)
	}
}
func existing(command, root string) error {
	b, e := os.ReadFile(filepath.Join(root, "state.json"))
	if e != nil {
		return e
	}
	var s State
	if e = json.Unmarshal(b, &s); e != nil {
		return e
	}
	if s.Owner != owner || s.WorkRoot != root || !clusterPattern.MatchString(s.Cluster) || !inside(root, s.Kubeconfig) || !inside(root, s.RunDirectory) {
		return errors.New("refusing unmanaged or invalid state")
	}
	if e = localDocker(&s); e != nil {
		return e
	}
	if command == "status" {
		fmt.Println(s.Status, s.URL)
		out, e := kubectl(&s, "get", "pods,services")
		fmt.Println(out)
		return e
	}
	kind, e := ensureTool(root, "kind")
	if e != nil {
		return e
	}
	if _, e = run("", kindEnv(&s), kind, "delete", "cluster", "--name", s.Cluster, "--kubeconfig", s.Kubeconfig); e != nil {
		return e
	}
	s.Status = "STOPPED"
	if e = save(&s); e != nil {
		return e
	}
	if e = os.Rename(filepath.Join(root, "state.json"), filepath.Join(s.RunDirectory, "stopped-state.json")); e != nil {
		return e
	}
	fmt.Println("Deleted only tool-owned local cluster:", s.Cluster, "Reports/source checkouts retained.")
	return nil
}
func inside(root, path string) bool {
	rel, e := filepath.Rel(root, path)
	return e == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel)
}
func ensureTool(root, name string) (string, error) {
	if path, e := exec.LookPath(name); e == nil {
		return path, nil
	}
	if runtime.GOOS != "windows" && runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		return "", errors.New("unsupported OS")
	}
	if runtime.GOARCH != "amd64" && runtime.GOARCH != "arm64" {
		return "", errors.New("unsupported architecture")
	}
	bin := filepath.Join(root, "bin", name)
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}
	if _, e := os.Stat(bin); e == nil {
		return bin, nil
	}
	if e := os.MkdirAll(filepath.Dir(bin), 0700); e != nil {
		return "", e
	}
	suffix := runtime.GOOS + "-" + runtime.GOARCH
	var downloadURL, checksumURL string
	if name == "kind" {
		downloadURL = "https://github.com/kubernetes-sigs/kind/releases/download/" + kindVersion + "/kind-" + suffix
		checksumURL = downloadURL + ".sha256sum"
	} else {
		extension := ".tar.gz"
		if runtime.GOOS == "windows" {
			extension = ".zip"
		}
		downloadURL = "https://get.helm.sh/helm-" + helmVersion + "-" + suffix + extension
		checksumURL = downloadURL + ".sha256sum"
	}
	checksum, e := fetch(checksumURL, 1<<20)
	if e != nil {
		return "", e
	}
	fields := strings.Fields(string(checksum))
	if len(fields) == 0 {
		return "", errors.New("empty checksum")
	}
	data, e := fetch(downloadURL, 256<<20)
	if e != nil {
		return "", e
	}
	sum := sha256.Sum256(data)
	if hex.EncodeToString(sum[:]) != strings.ToLower(fields[0]) {
		return "", errors.New("download checksum mismatch")
	}
	if name == "helm" {
		data, e = extractHelm(data, runtime.GOOS == "windows")
		if e != nil {
			return "", e
		}
	}
	if e = os.WriteFile(bin, data, 0700); e != nil {
		return "", e
	}
	return bin, nil
}
func fetch(url string, max int64) ([]byte, error) {
	client := &http.Client{Timeout: 120 * time.Second}
	r, e := client.Get(url)
	if e != nil {
		return nil, e
	}
	defer r.Body.Close()
	if r.StatusCode != 200 {
		return nil, fmt.Errorf("download returned HTTP %d", r.StatusCode)
	}
	b, e := io.ReadAll(io.LimitReader(r.Body, max+1))
	if int64(len(b)) > max {
		return nil, errors.New("download too large")
	}
	return b, e
}
func extractHelm(data []byte, isZip bool) ([]byte, error) {
	if isZip {
		r, e := zip.NewReader(bytes.NewReader(data), int64(len(data)))
		if e != nil {
			return nil, e
		}
		for _, f := range r.File {
			if filepath.Base(f.Name) == "helm.exe" {
				reader, e := f.Open()
				if e != nil {
					return nil, e
				}
				defer reader.Close()
				return io.ReadAll(io.LimitReader(reader, 128<<20))
			}
		}
	} else {
		gz, e := gzip.NewReader(bytes.NewReader(data))
		if e != nil {
			return nil, e
		}
		defer gz.Close()
		r := tar.NewReader(gz)
		for {
			h, e := r.Next()
			if errors.Is(e, io.EOF) {
				break
			}
			if e != nil {
				return nil, e
			}
			if filepath.Base(h.Name) == "helm" && h.Typeflag == tar.TypeReg {
				return io.ReadAll(io.LimitReader(r, 128<<20))
			}
		}
	}
	return nil, errors.New("helm executable absent from archive")
}
