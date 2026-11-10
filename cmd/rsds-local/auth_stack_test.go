package main

import (
	"crypto/ecdsa"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLocalSigningKeysMatchAndExpire(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "keys")
	if err := generateLocalSigningMaterial(directory); err != nil {
		t.Fatal(err)
	}
	privateBytes, err := os.ReadFile(filepath.Join(directory, "private.pem"))
	if err != nil {
		t.Fatal(err)
	}
	privateBlock, _ := pem.Decode(privateBytes)
	key, err := x509.ParsePKCS8PrivateKey(privateBlock.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	certBytes, err := os.ReadFile(filepath.Join(directory, "active.crt"))
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode(certBytes)
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	if cert.PublicKey.(*rsa.PublicKey).N.Cmp(key.(*rsa.PrivateKey).N) != 0 {
		t.Fatal("Signing key and public certificate mismatch")
	}
	if time.Until(cert.NotAfter) > 49*time.Hour || time.Until(cert.NotAfter) < 47*time.Hour {
		t.Fatal("Local certificate lifetime must be bounded")
	}
	if err = cert.CheckSignature(cert.SignatureAlgorithm, cert.RawTBSCertificate, cert.Signature); err != nil {
		t.Fatal(err)
	}
	appleBytes, err := os.ReadFile(filepath.Join(directory, "apple.p8"))
	if err != nil {
		t.Fatal(err)
	}
	appleBlock, _ := pem.Decode(appleBytes)
	apple, err := x509.ParsePKCS8PrivateKey(appleBlock.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	publicBytes, err := os.ReadFile(filepath.Join(directory, "apple-public.pem"))
	if err != nil {
		t.Fatal(err)
	}
	publicBlock, _ := pem.Decode(publicBytes)
	public, err := x509.ParsePKIXPublicKey(publicBlock.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	if !apple.(*ecdsa.PrivateKey).PublicKey.Equal(public) {
		t.Fatal("Apple fixture does not have the matching public client key")
	}
}

func TestBootstrapRetryPreservesKeysAndRejectsPartialMaterial(t *testing.T) {
	directory := t.TempDir()
	if err := ensureLocalSigningMaterial(directory); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(filepath.Join(directory, "private.pem"))
	if err != nil {
		t.Fatal(err)
	}
	if err := ensureLocalSigningMaterial(directory); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(directory, "private.pem"))
	if err != nil || string(before) != string(after) {
		t.Fatal("retry rotated signing material")
	}
	if err := os.Remove(filepath.Join(directory, "apple.p8")); err != nil {
		t.Fatal(err)
	}
	if err := ensureLocalSigningMaterial(directory); err == nil {
		t.Fatal("partial material must fail without overwriting")
	}
}
