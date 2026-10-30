package main

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"time"
)

// Only local runs receive throwaway keys. Production provisioning is a separate process.
func generateLocalSigningMaterial(directory string) error {
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	key, err := rsa.GenerateKey(rand.Reader, 3072)
	if err != nil {
		return err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return err
	}
	now := time.Now()
	template := &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: "rsds-auth-local-only"}, NotBefore: now.Add(-time.Minute), NotAfter: now.Add(48 * time.Hour), KeyUsage: x509.KeyUsageDigitalSignature}
	cert, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return err
	}
	der, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(directory, "private.pem"), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), 0600); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(directory, "active.crt"), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert}), 0600)
}

func prepareAuthStack(s *State) error {
	keys := filepath.Join(s.RunDirectory, "auth-keys")
	if err := generateLocalSigningMaterial(keys); err != nil {
		return err
	}
	if _, err := kubectl(s, "create", "namespace", "rsds-local-test"); err != nil {
		return err
	}
	if _, err := kubectl(s, "create", "secret", "generic", "rsds-local-auth-signing", "--from-file=private.pem="+filepath.Join(keys, "private.pem")); err != nil {
		return err
	}
	_, err := kubectl(s, "create", "secret", "generic", "rsds-local-auth-trust", "--from-file=active.crt="+filepath.Join(keys, "active.crt"))
	return err
}
