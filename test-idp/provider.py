"""Local-only OAuth2/OIDC protocol boundary. Never deploy this fixture as a real identity provider."""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.exceptions import InvalidSignature

PROVIDERS = {'google', 'microsoft', 'apple', 'github', 'facebook'}
OIDC = {'google', 'microsoft', 'apple'}
PKCE = {'google', 'microsoft', 'github'}
ISSUER = os.environ.get('ISSUER_BASE', 'http://rsds-local-idp:9000')
KEYS = {provider: rsa.generate_private_key(public_exponent=65537, key_size=3072) for provider in PROVIDERS}
INVALID_KEY = rsa.generate_private_key(public_exponent=65537, key_size=3072)
CODES = {}
TOKENS = {}
LOCK = threading.Lock()
APPLE_CLIENT_KEY = serialization.load_pem_public_key(Path('/run/client-trust/apple-public.pem').read_bytes())


def verify_client(provider, token):
    if provider != 'apple':
        return hmac.compare_digest(token, 'local-fixture-secret')
    try:
        header, payload, signature = token.split('.')
        metadata = json.loads(base64.urlsafe_b64decode(header + '=='))
        claims = json.loads(base64.urlsafe_b64decode(payload + '=='))
        raw = base64.urlsafe_b64decode(signature + '==')
        if len(raw) != 64 or metadata.get('alg') != 'ES256' or metadata.get('kid') != 'local-apple-client':
            return False
        der = utils.encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        APPLE_CLIENT_KEY.verify(der, (header + '.' + payload).encode(), ec.ECDSA(hashes.SHA256()))
        now = time.time()
        audience = claims.get('aud')
        return (claims.get('iss') == 'LOCALTEAM' and claims.get('sub') == 'local-apple'
                and (audience == 'https://appleid.apple.com' or audience == ['https://appleid.apple.com'])
                and claims.get('iat', now + 100) <= now + 30 and now < claims.get('exp', 0) <= now + 330)
    except (ValueError, KeyError, TypeError, InvalidSignature):
        return False


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def encoded(value):
    return b64(json.dumps(value, separators=(',', ':')).encode())


def jwt(provider, request, invalid):
    now = int(time.time())
    header = encoded({'alg': 'RS256', 'kid': provider + '-fixture', 'typ': 'JWT'})
    profile = request.get('fixture_profile', {'sub': 'alice-subject', 'email': 'alice@example.test', 'email_verified': True})
    claims = encoded({'iss': ISSUER + '/' + provider, 'sub': profile['sub'], 'aud': request['client_id'],
                      'iat': now, 'exp': now + 120, 'nonce': request['nonce'], 'name': 'Alice',
                      'email': profile.get('email'), 'email_verified': profile.get('email_verified', False),
                      'hd': 'example.test' if profile.get('email_verified') else None, 'roles': ['ADMIN', 'JOB_REPLY']})
    message = (header + '.' + claims).encode()
    key = INVALID_KEY if invalid else KEYS[provider]
    return message.decode() + '.' + b64(key.sign(message, padding.PKCS1v15(), hashes.SHA256()))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Codes/tokens and callback state must not enter logs.

    def send(self, code, body, content_type='application/json'):
        content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def parsed(self):
        path = urlsplit(self.path)
        parts = path.path.strip('/').split('/')
        provider = parts[0] if len(parts) == 2 else ''
        if provider not in PROVIDERS:
            self.send(404, {'error': 'unknown_provider'})
            return None
        return provider, parts[1], {key: values[0] for key, values in parse_qs(path.query).items()}

    def do_GET(self):
        if self.path == '/health':
            return self.send(200, {'status': 'UP'})
        parsed = self.parsed()
        if parsed is None:
            return
        provider, endpoint, query = parsed
        if endpoint == 'jwks':
            public = KEYS[provider].public_key().public_numbers()
            return self.send(200, {'keys': [{'kty': 'RSA', 'use': 'sig', 'alg': 'RS256', 'kid': provider + '-fixture',
                                           'n': b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, 'big')),
                                           'e': b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, 'big'))}]})
        if endpoint in {'userinfo', 'emails'}:
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            with LOCK:
                owner = TOKENS.get(token)
            if not owner or owner['provider'] != provider:
                return self.send(401, {'error': 'invalid_token'})
            profile = owner['profile']
            if endpoint == 'emails':
                if provider != 'github' or 'user:email' not in owner['scope'].split():
                    return self.send(403, {'error': 'missing_email_scope'})
                return self.send(200, [{'email': profile.get('email'), 'primary': True, 'verified': profile.get('email_verified', False)}])
            # GitHub's public email is deliberately absent: the backend must load /emails.
            return self.send(200, {'sub': profile['sub'], 'id': profile['sub'], 'name': 'Alice',
                                   'email': None if provider == 'github' else profile.get('email'), 'roles': ['ADMIN']})
        if endpoint != 'authorize':
            return self.send(404, {'error': 'not_found'})
        callback = urlsplit(query.get('redirect_uri', ''))
        expected = '/api/auth/login/oauth2/code/' + provider
        host = callback.hostname or ''
        local_host = host == '127.0.0.1' or (host.startswith('rsds-local-') and host.endswith('-control-plane'))
        valid = (local_host and callback.scheme == 'http' and callback.path == expected and not callback.query and not callback.fragment
                 and query.get('client_id') == 'local-' + provider and query.get('response_type') == 'code' and query.get('state'))
        if provider in PKCE:
            valid = valid and query.get('code_challenge_method') == 'S256' and query.get('code_challenge')
        if provider in OIDC:
            valid = valid and query.get('nonce') and 'openid' in query.get('scope', '').split()
        if provider == 'apple':
            valid = valid and query.get('response_mode') == 'form_post'
        if not valid:
            return self.send(400, {'error': 'invalid_authorization_request'})
        request_id = secrets.token_urlsafe(24)
        with LOCK:
            CODES['request:' + request_id] = (provider, query, time.time())
        form = '<input type="hidden" name="request" value="' + html.escape(request_id, quote=True) + '">'
        buttons = ''.join('<button name="choice" value="' + value + '">' + label + '</button>' for value, label in
                          [('allow', 'Continue as Alice'), ('deny', 'Deny consent'), ('invalid', 'Invalid token signature'),
                           ('unverified', 'Continue with unverified email'), ('missing', 'Continue without email'),
                           ('changed', 'Continue as Alice with changed email'), ('relay', 'Continue with Apple relay')])
        self.send(200, '<!doctype html><html lang="en"><head><title>Local protocol fixture</title></head><body><h1>Local ' +
                  provider + ' identity provider</h1><p>Test fixture only; no real provider account is used.</p><form method="post" action="/__test/idp/' +
                  provider + '/decision">' + form + buttons + '</form></body></html>', 'text/html')

    def do_POST(self):
        parsed = self.parsed()
        if parsed is None:
            return
        provider, endpoint, _ = parsed
        length = int(self.headers.get('Content-Length', '0'))
        if length > 16384:
            return self.send(413, {'error': 'too_large'})
        fields = {key: values[0] for key, values in parse_qs(self.rfile.read(length).decode()).items()}
        if endpoint == 'decision':
            with LOCK:
                item = CODES.pop('request:' + fields.get('request', ''), None)
            if not item or item[0] != provider or time.time() - item[2] > 120:
                return self.send(400, {'error': 'expired_request'})
            _, request, _ = item
            choice = fields.get('choice', '')
            suffix = hashlib.sha256(request['state'].encode()).hexdigest()[:16]
            profile = {'sub': 'alice-subject', 'email': 'alice@example.test', 'email_verified': True}
            if choice == 'unverified':
                profile = {'sub': 'unverified-' + suffix, 'email': 'verify-' + suffix + '@example.test', 'email_verified': False}
            elif choice == 'missing':
                profile = {'sub': 'missing-' + suffix}
            elif choice == 'changed':
                profile['email'] = 'changed@example.test'
            elif choice == 'relay':
                profile = {'sub': 'relay-subject', 'email': 'alice@privaterelay.appleid.com', 'email_verified': True}
            request['fixture_profile'] = profile
            result = {'state': request['state']}
            if fields.get('choice') == 'deny':
                result['error'] = 'access_denied'
            else:
                code = secrets.token_urlsafe(32)
                with LOCK:
                    CODES[code] = (provider, request, fields.get('choice') == 'invalid', time.time())
                result['code'] = code
            if provider == 'apple':
                hidden = ''.join('<input type="hidden" name="' + name + '" value="' + html.escape(value, quote=True) + '">' for name, value in result.items())
                return self.send(200, '<!doctype html><html><body><form id="callback" method="post" action="' + html.escape(request['redirect_uri'], quote=True) +
                                 '">' + hidden + '</form><script>document.getElementById("callback").submit()</script></body></html>', 'text/html')
            self.send_response(302)
            self.send_header('Location', request['redirect_uri'] + '?' + urlencode(result))
            self.send_header('Cache-Control', 'no-store')
            return self.end_headers()
        if endpoint != 'token':
            return self.send(404, {'error': 'not_found'})
        with LOCK:
            item = CODES.pop(fields.get('code', ''), None)
        if not item or item[0] != provider or time.time() - item[3] > 120:
            return self.send(400, {'error': 'invalid_grant'})
        _, request, invalid, _ = item
        valid = (fields.get('grant_type') == 'authorization_code' and fields.get('client_id') == request['client_id']
                 and verify_client(provider, fields.get('client_secret', ''))
                 and fields.get('redirect_uri') == request['redirect_uri'])
        if provider in PKCE:
            valid = valid and hmac.compare_digest(b64(hashlib.sha256(fields.get('code_verifier', '').encode()).digest()), request['code_challenge'])
        if not valid:
            return self.send(400, {'error': 'invalid_grant'})
        access = secrets.token_urlsafe(32)
        with LOCK:
            TOKENS[access] = {'provider': provider, 'profile': request['fixture_profile'], 'scope': request.get('scope', '')}
        response = {'access_token': access, 'token_type': 'Bearer', 'expires_in': 120, 'scope': request.get('scope', '')}
        if provider in OIDC:
            response['id_token'] = jwt(provider, request, invalid)
        self.send(200, response)


ThreadingHTTPServer(('0.0.0.0', 9000), Handler).serve_forever()

