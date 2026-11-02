package main

import (
	"errors"
	"net/url"
	"os"
	"strings"
)

// Only provider configuration can be imported: never arbitrary Spring/AWS overrides.
func validateProviderFile(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return errors.New("cannot read private OAuth env file")
	}
	if len(data) > 65536 {
		return errors.New("OAuth env file exceeds 64 KiB")
	}
	allowed := map[string]bool{"RSDS_AUTH_PUBLIC_BASE_URL": true, "RSDS_AUTH_PROVIDERS_MICROSOFT_TENANT": true, "RSDS_AUTH_PROVIDERS_FACEBOOK_GRAPH_VERSION": true}
	for _, provider := range []string{"GOOGLE", "FACEBOOK", "MICROSOFT", "GITHUB"} {
		for _, suffix := range []string{"CLIENT_ID", "CLIENT_SECRET"} {
			allowed["RSDS_AUTH_PROVIDERS_"+provider+"_"+suffix] = true
		}
	}
	values := map[string]string{}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok || !allowed[key] || values[key] != "" || value == "" {
			return errors.New("invalid, duplicate or unsupported OAuth configuration entry (values withheld)")
		}
		values[key] = value
	}
	origin, err := url.Parse(values["RSDS_AUTH_PUBLIC_BASE_URL"])
	if err != nil || origin.Host == "" || origin.User != nil || origin.RawQuery != "" || origin.Fragment != "" || origin.Path != "" || (origin.Scheme != "https" && !(origin.Scheme == "http" && (origin.Hostname() == "127.0.0.1" || origin.Hostname() == "localhost"))) {
		return errors.New("OAuth public base URL must be an exact HTTPS origin or HTTP loopback origin, without a trailing slash")
	}
	count := 0
	for _, provider := range []string{"GOOGLE", "FACEBOOK", "MICROSOFT", "GITHUB"} {
		prefix := "RSDS_AUTH_PROVIDERS_" + provider + "_"
		id, secret := values[prefix+"CLIENT_ID"], values[prefix+"CLIENT_SECRET"]
		if (id == "") != (secret == "") {
			return errors.New("each configured provider needs both client ID and secret")
		}
		if id != "" {
			count++
		}
		if id != "" && provider == "MICROSOFT" && values[prefix+"TENANT"] == "" {
			return errors.New("Microsoft requires its explicit permitted tenant UUID")
		}
		if id != "" && provider == "FACEBOOK" && values[prefix+"GRAPH_VERSION"] == "" {
			return errors.New("Facebook requires its supported Graph API version")
		}
	}
	if count == 0 {
		return errors.New("configure at least one real OAuth application; user passwords are not OAuth configuration")
	}
	return nil
}
