"""폰에서 카메라를 쓰려면 HTTPS 가 필요하다. 로컬 전용 자체 서명 인증서를 만든다.

브라우저는 `localhost` 가 아닌 주소에서는 HTTPS 여야만 `getUserMedia`(카메라)를
허용한다. 그래서 같은 와이파이의 폰에서 `http://192.168.x.x:8000` 으로 들어가면
화면은 보이지만 카메라가 절대 열리지 않는다.

이 스크립트는 PC 의 랜 IP 를 SAN 에 넣은 자체 서명 인증서를 만든다. 폰에서 처음
접속할 때 "안전하지 않음" 경고가 뜨는데, 고급 -> 계속 진행을 누르면 그 이후로는
보안 컨텍스트로 취급돼 카메라가 열린다. 인증서는 이 컴퓨터 밖으로 나가지 않고,
서버도 공인망에 노출되지 않는다(같은 와이파이 안에서만 접근 가능).

    python tools/make_cert.py
    python -m uvicorn server.main:app --host 0.0.0.0 --port 8443 \
        --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
"""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def local_ips() -> list[str]:
    """이 컴퓨터의 랜 IPv4 주소들."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")):
                ips.add(ip)
    except socket.gaierror:
        pass
    # 기본 경로로 나가는 인터페이스 주소도 확인 (실제로 전송하지는 않는다)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    return sorted(ips)


def make(out_dir: Path, extra_ips: list[str], days: int = 825) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    key_path = out_dir / "key.pem"
    cert_path = out_dir / "cert.pem"

    ips = sorted(set(local_ips() + extra_ips))
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(socket.gethostname()),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    for ip in ips:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "TennisVision Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TennisVision"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path, ips


def main() -> None:
    ap = argparse.ArgumentParser(description="로컬 HTTPS 용 자체 서명 인증서 생성")
    ap.add_argument("--out", default="certs")
    ap.add_argument("--ip", action="append", default=[], help="추가로 넣을 IP (핫스팟 등)")
    ap.add_argument("--port", type=int, default=8443)
    args = ap.parse_args()

    key_path, cert_path, ips = make(Path(args.out), args.ip)
    print(f"인증서 생성 완료\n  키   {key_path}\n  인증서 {cert_path}")
    print(f"  포함된 주소: localhost, 127.0.0.1, {', '.join(ips) or '(랜 IP 없음)'}")
    print("\n서버 실행:")
    print(f"  python -m uvicorn server.main:app --host 0.0.0.0 --port {args.port} \\")
    print(f"      --ssl-keyfile {key_path} --ssl-certfile {cert_path}")
    print("\n폰에서 접속:")
    for ip in ips:
        print(f"  https://{ip}:{args.port}")
    print("\n처음 한 번은 '연결이 비공개로 설정되어 있지 않습니다' 경고가 뜹니다.")
    print("고급 -> 안전하지 않음(계속)을 누르면 그 뒤로 카메라가 열립니다.")


if __name__ == "__main__":
    main()
