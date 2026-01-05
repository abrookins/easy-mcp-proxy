"""Nginx reverse proxy CLI commands."""

import subprocess
import sys
from pathlib import Path

import click


@click.group()
def nginx():
    """Manage nginx reverse proxy for HTTPS termination."""
    pass


@nginx.command("generate")
@click.argument("server_name")
@click.option(
    "--port", "-p", default=8000, type=int, help="Backend port (default: 8000)"
)
@click.option("--host", default="127.0.0.1", help="Backend host (default: 127.0.0.1)")
@click.option("--ssl-cert", default=None, help="Path to SSL certificate")
@click.option("--ssl-key", default=None, help="Path to SSL private key")
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@click.option(
    "--timeout", default=300, type=int, help="Proxy read/send timeout in seconds"
)
def nginx_generate(
    server_name: str,
    port: int,
    host: str,
    ssl_cert: str | None,
    ssl_key: str | None,
    output: str | None,
    timeout: int,
):
    """Generate nginx configuration for HTTPS reverse proxy.

    SERVER_NAME is the domain name (e.g., mcp.example.com)
    """
    from mcp_proxy.nginx import NginxConfig, generate_nginx_config

    config = NginxConfig(
        server_name=server_name,
        backend_port=port,
        backend_host=host,
        ssl_certificate=ssl_cert,
        ssl_certificate_key=ssl_key,
        proxy_read_timeout=timeout,
        proxy_send_timeout=timeout,
    )

    nginx_conf = generate_nginx_config(config)

    if output:
        Path(output).write_text(nginx_conf)
        click.echo(f"Nginx configuration written to {output}")
    else:
        click.echo(nginx_conf)


@nginx.command("install")
@click.argument("server_name")
@click.option(
    "--port", "-p", default=8000, type=int, help="Backend port (default: 8000)"
)
@click.option("--ssl-cert", default=None, help="Path to SSL certificate")
@click.option("--ssl-key", default=None, help="Path to SSL private key")
@click.option(
    "--nginx-dir",
    default="/etc/nginx/sites-available",
    help="Nginx sites directory",
)
@click.option(
    "--enable/--no-enable", default=True, help="Enable the site after install"
)
@click.option("--reload/--no-reload", default=True, help="Reload nginx after install")
def nginx_install(
    server_name: str,
    port: int,
    ssl_cert: str | None,
    ssl_key: str | None,
    nginx_dir: str,
    enable: bool,
    reload: bool,
):
    """Install nginx configuration and optionally enable it.

    SERVER_NAME is the domain name (e.g., mcp.example.com)

    Requires root/sudo privileges.
    """
    from mcp_proxy.nginx import NginxConfig, generate_nginx_config

    config = NginxConfig(
        server_name=server_name,
        backend_port=port,
        ssl_certificate=ssl_cert,
        ssl_certificate_key=ssl_key,
    )

    nginx_conf = generate_nginx_config(config)

    sites_available = Path(nginx_dir)
    sites_enabled = sites_available.parent / "sites-enabled"
    config_file = sites_available / f"mcp-proxy-{server_name}"

    try:
        config_file.write_text(nginx_conf)
        click.echo(f"Configuration written to {config_file}")
    except PermissionError:
        click.echo("Error: Permission denied. Try running with sudo.", err=True)
        raise SystemExit(1)
    except FileNotFoundError:
        click.echo(f"Error: Directory not found: {nginx_dir}", err=True)
        raise SystemExit(1)

    if enable:
        symlink = sites_enabled / config_file.name
        if symlink.exists() or symlink.is_symlink():
            click.echo(f"Site already enabled: {symlink}")
        else:
            symlink.symlink_to(config_file)
            click.echo(f"Site enabled: {symlink}")

    if reload:
        result = subprocess.run(
            ["nginx", "-t"],
            capture_output=True,
            text=True,  # noqa: S603, S607
        )
        if result.returncode != 0:
            click.echo(f"Nginx config test failed:\n{result.stderr}", err=True)
            raise SystemExit(1)

        subprocess.run(
            ["systemctl", "reload", "nginx"],  # noqa: S603, S607
            check=True,
        )
        click.echo("Nginx reloaded successfully")


@nginx.command("certbot")
@click.argument("server_name")
@click.option("--email", "-e", required=True, help="Email for Let's Encrypt")
@click.option("--dry-run", is_flag=True, help="Test without saving certificate")
def nginx_certbot(server_name: str, email: str, dry_run: bool):
    """Obtain SSL certificate using certbot (requires domain name).

    SERVER_NAME is the domain name (e.g., mcp.example.com)

    Requires certbot to be installed and root/sudo privileges.
    """
    cmd = [
        "certbot",
        "certonly",
        "--nginx",
        "-d",
        server_name,
        "--email",
        email,
        "--agree-tos",
        "--non-interactive",
    ]

    if dry_run:
        cmd.append("--dry-run")

    click.echo(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)  # noqa: S603

    if result.returncode != 0:
        click.echo("Certbot failed. Is certbot installed?", err=True)
        click.echo("Install with: sudo apt install certbot python3-certbot-nginx")
        sys.exit(1)

    if not dry_run:
        click.echo(f"\nCertificate obtained for {server_name}")
        click.echo("You can now run: mcp-proxy nginx install " + server_name)


@nginx.command("self-signed")
@click.argument("name")
@click.option(
    "--output-dir",
    "-o",
    default=".",
    help="Output directory for certificate files",
)
@click.option("--days", default=365, type=int, help="Certificate validity in days")
def nginx_self_signed(name: str, output_dir: str, days: int):
    """Generate a self-signed SSL certificate (no domain required).

    NAME can be a domain, hostname, or IP address (e.g., localhost, 192.168.1.100)

    Creates {name}.crt and {name}.key files in the output directory.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cert_file = out / f"{name}.crt"
    key_file = out / f"{name}.key"

    # Generate private key and self-signed certificate using openssl
    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:4096",
        "-keyout",
        str(key_file),
        "-out",
        str(cert_file),
        "-days",
        str(days),
        "-nodes",  # No passphrase
        "-subj",
        f"/CN={name}",
        "-addext",
        f"subjectAltName=DNS:{name},IP:{name}"
        if _looks_like_ip(name)
        else f"subjectAltName=DNS:{name}",
    ]

    click.echo(f"Generating self-signed certificate for {name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603

    if result.returncode != 0:
        click.echo(f"OpenSSL failed: {result.stderr}", err=True)
        sys.exit(1)

    click.echo(f"Certificate: {cert_file}")
    click.echo(f"Private key: {key_file}")
    click.echo("\nUse with nginx generate:")
    click.echo(
        f"  mcp-proxy nginx generate {name} --ssl-cert {cert_file} --ssl-key {key_file}"
    )
    click.echo(
        "\nNote: Clients will need to trust this certificate or disable verification."
    )


def _looks_like_ip(name: str) -> bool:
    """Check if name looks like an IP address."""
    parts = name.split(".")
    if len(parts) == 4:
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
    return False
