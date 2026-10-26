from __future__ import annotations
import datetime
import ipaddress
import logging
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

CERT_NAME = "xr-cert.pem"
KEY_NAME = "xr-key.pem"
_VALID_DAYS = 397


def lan_addresses() -> list[str]:
    """IPv4 addresses the headset can reach this PC on, most likely first."""
    primary = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # No packet is sent; this only asks the OS which interface routes out.
            s.connect(("10.255.255.255", 1))
            primary = s.getsockname()[0]
    except OSError:
        pass
    others = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            others.add(info[4][0])
    except OSError:
        pass
    addrs = [primary] if primary else []
    addrs += sorted(others - {primary})
    return [a for a in addrs if not a.startswith(("127.", "169.254.", "0."))]


def ensure_certificate(cert_dir: Path, hosts: list[str]) -> tuple[Path, Path]:
    """Return a self-signed cert/key pair covering localhost and `hosts`.

    WebXR only runs on secure (HTTPS) pages, so the Quest needs the bridge to
    serve TLS. The pair is reused across runs and regenerated when this PC's
    addresses change or it is close to expiring.
    """
    cert_path = cert_dir / CERT_NAME
    key_path = cert_dir / KEY_NAME
    wanted = {"localhost", "127.0.0.1", *hosts}
    if cert_path.exists() and key_path.exists() and _covers(cert_path, wanted):
        return cert_path, key_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Midi Gestures XR bridge")])
    sans: list[x509.GeneralName] = []
    for h in sorted(wanted):
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            sans.append(x509.DNSName(h))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=_VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_dir.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Created self-signed certificate %s for %s", cert_path, ", ".join(sorted(wanted)))
    return cert_path, key_path


def _covers(cert_path: Path, wanted: set[str]) -> bool:
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
        names |= set(san.get_values_for_type(x509.DNSName))
        expires = cert.not_valid_after_utc
        soon = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
        return wanted <= names and expires > soon
    except Exception as e:
        logger.debug("Existing certificate unusable (%s), regenerating", e)
        return False
