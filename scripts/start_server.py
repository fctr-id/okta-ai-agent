import subprocess
import threading
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Change to project root directory
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def stream_output(stream, prefix):
    """Stream output from a pipe to stdout"""
    for line in iter(stream.readline, ""):
        if line:
            print(f"{prefix}: {line.strip()}")
    stream.close()

def run_command(command):
    """Run a shell command and print output from both stdout and stderr"""
    print(f"Executing: {command}")
    
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )
    
    # Set up threads to stream both stdout and stderr
    stdout_thread = threading.Thread(target=stream_output, args=(process.stdout, "OUT"))
    stderr_thread = threading.Thread(target=stream_output, args=(process.stderr, "ERR"))
    
    # Set as daemon threads so they exit when main thread exits
    stdout_thread.daemon = True
    stderr_thread.daemon = True
    
    # Start the threads
    stdout_thread.start()
    stderr_thread.start()
    
    # Wait for the process to complete
    return_code = process.wait()
    
    # Give the threads a moment to finish printing any remaining output
    stdout_thread.join(1)
    stderr_thread.join(1)
    
    if return_code != 0:
        print(f"Command exited with return code {return_code}")
        return False
    
    return True

def generate_self_signed_cert(cert_path, key_path):
    """Generate self-signed certificates using the cryptography library (no OpenSSL needed)"""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import ipaddress
    except ImportError:
        print("Installing required package: cryptography")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import ipaddress

    # Generate private key
    print("Generating private key...")
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    # Write private key to file
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Generate certificate
    print("Generating self-signed certificate...")
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"State"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"City"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Okta AI Agent"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, u"Development"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost")
    ])
    
    # Certificate is valid for 10 years - using timezone-aware datetime
    valid_from = datetime.now(timezone.utc)
    valid_to = valid_from + timedelta(days=3650)
    
    # Build certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))
            ]),
            critical=False
        )
        .sign(key, hashes.SHA256())
    )
    
    # Write certificate to file
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print(f"Certificate and key generated and saved to {cert_path} and {key_path}")

def ensure_certificates():
    """Generate SSL certificates if they don't exist"""
    cert_dir = Path("src/backend/certs")
    cert_dir.mkdir(exist_ok=True, parents=True)
    
    key_path = cert_dir / "key.pem"
    cert_path = cert_dir / "cert.pem"
    
    if not key_path.exists() or not cert_path.exists():
        print("Generating SSL certificates...")
        generate_self_signed_cert(cert_path, key_path)
    else:
        print("Using existing SSL certificates")
    
    return str(key_path), str(cert_path)

def stream_output(stream, prefix):
    """Stream output from a pipe to stdout with minimal modification"""
    for line in iter(stream.readline, ""):
        if line:
            # Pass through log lines as-is, tag other output
            line = line.strip()
            if any(log_level in line for log_level in ["INFO:", "WARNING:", "ERROR:", "DEBUG:"]):
                print(line)
            else:
                print(f"{prefix}: {line}")
    stream.close()

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Start the Okta AI Agent server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind to")
    parser.add_argument("--no-https", action="store_true", help="Run without HTTPS (not recommended)")
    parser.add_argument("--log-level", default="info", help="Logging level")
    args = parser.parse_args()
    
    # Run the FastAPI server
    print("Starting server...")
    
    if args.no_https:
        print("WARNING: Running without HTTPS. This is not recommended for production use.")
        command = f"venv\\Scripts\\python -m uvicorn src.api.main:app --host {args.host} --port {args.port} --log-level {args.log_level}"
        run_command(command)
    else:
        # Generate certificates if needed
        key_path, cert_path = ensure_certificates()
        print(f"Starting secure server on https://{args.host}:{args.port}")
        
        # Run with HTTPS
        command = (
            f"venv\\Scripts\\python -m uvicorn src.api.main:app --host {args.host} "
            f"--port {args.port} --log-level {args.log_level} "
            f"--ssl-keyfile {key_path} --ssl-certfile {cert_path}"
        )
        run_command(command)