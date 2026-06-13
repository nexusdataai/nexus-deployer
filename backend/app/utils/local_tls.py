"""Self-signed TLS certificate management for the local Electron backend.

The Electron desktop app talks to the FastAPI backend over the loopback
interface only (127.0.0.1). To eliminate cleartext-HTTP SAST findings
(CWE-319) without depending on a public CA, we generate a self-signed
certificate at first launch, persist it under the user's data directory,
and start uvicorn with TLS enabled.

The Electron main process pins the certificate's SPKI hash via the
`STARHUB_LOCAL_TLS_SPKI` environment variable and the
`ignore-certificate-errors-spki-list` Chromium switch, so renderer
fetches succeed without trusting any other certificate.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

CERT_FILENAME = "cert.pem"
KEY_FILENAME = "key.pem"
SPKI_FILENAME = "spki.txt"


def get_local_tls_dir() -> Path:
    """Return the directory holding the local TLS material."""
    override = os.getenv("STARHUB_LOCAL_TLS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".nexus" / "local-tls"


def _spki_pin_b64(public_key) -> str:
    """Compute the base64-encoded SHA-256 of the SubjectPublicKeyInfo."""
    from cryptography.hazmat.primitives import serialization

    spki_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(spki_der).digest()
    return base64.b64encode(digest).decode("ascii")


def _generate_cert(cert_path: Path, key_path: Path, spki_path: Path) -> str:
    """Generate a fresh self-signed certificate and key. Returns the SPKI pin."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from ipaddress import ip_address

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StarHub Deployer (local)"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365 * 5))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ip_address("127.0.0.1")),
                x509.IPAddress(ip_address("::1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(key_path, 0o600)
    except (OSError, NotImplementedError):
        pass

    spki_pin = _spki_pin_b64(private_key.public_key())
    spki_path.write_text(spki_pin)
    logger.info("Generated local-TLS cert at %s (SPKI pin %s)", cert_path, spki_pin)
    return spki_pin


def ensure_local_tls() -> Tuple[Path, Path, str]:
    """Ensure a local TLS cert/key exist, regenerating if missing or expired.

    Returns ``(cert_path, key_path, spki_pin_b64)``.
    """
    tls_dir = get_local_tls_dir()
    cert_path = tls_dir / CERT_FILENAME
    key_path = tls_dir / KEY_FILENAME
    spki_path = tls_dir / SPKI_FILENAME

    needs_regen = not (cert_path.exists() and key_path.exists() and spki_path.exists())
    if not needs_regen:
        try:
            from cryptography import x509

            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after
            if not_after.tzinfo is None:
                not_after = not_after.replace(tzinfo=timezone.utc)
            if not_after - datetime.now(timezone.utc) < timedelta(days=30):
                needs_regen = True
        except Exception as exc:
            logger.warning("Existing local-TLS cert unreadable, regenerating: %s", exc)
            needs_regen = True

    if needs_regen:
        spki_pin = _generate_cert(cert_path, key_path, spki_path)
    else:
        spki_pin = spki_path.read_text().strip()

    return cert_path, key_path, spki_pin
