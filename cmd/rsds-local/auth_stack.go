package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
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
	if err = os.WriteFile(filepath.Join(directory, "active.crt"), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert}), 0600); err != nil {
		return err
	}
	apple, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return err
	}
	applePrivate, err := x509.MarshalPKCS8PrivateKey(apple)
	if err != nil {
		return err
	}
	applePublic, err := x509.MarshalPKIXPublicKey(&apple.PublicKey)
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(directory, "apple.p8"), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: applePrivate}), 0600); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(directory, "apple-public.pem"), pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: applePublic}), 0600)
}

func prepareAuthStack(s *State) error {
	keys := filepath.Join(s.RunDirectory, "auth-keys")
	if err := generateLocalSigningMaterial(keys); err != nil {
		return err
	}
	if _, err := kubectl(s, "create", "namespace", "rsds-local-test"); err != nil {
		return err
	}
	if _, err := kubectl(s, "create", "secret", "generic", "rsds-local-auth-signing", "--from-file=private.pem="+filepath.Join(keys, "private.pem"), "--from-file=apple.p8="+filepath.Join(keys, "apple.p8")); err != nil {
		return err
	}
	if _, err := kubectl(s, "create", "secret", "generic", "rsds-local-auth-trust", "--from-file=active.crt="+filepath.Join(keys, "active.crt")); err != nil {
		return err
	}
	_, err := kubectl(s, "create", "secret", "generic", "rsds-local-idp-client-trust", "--from-file=apple-public.pem="+filepath.Join(keys, "apple-public.pem"))
	return err
}
