"""Respaldo PostgreSQL en formato custom; obtiene credenciales desde .env."""
from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def pg_tool(name):
    found = shutil.which(name)
    if found:
        return found
    bin_override = os.environ.get("POSTGRES_BIN")
    if bin_override and (Path(bin_override) / f"{name}.exe").exists():
        return str(Path(bin_override) / f"{name}.exe")
    base = Path(r"C:\Program Files\PostgreSQL")
    versions = sorted((p for p in base.glob("*") if (p / "bin" / f"{name}.exe").exists()), reverse=True)
    return str(versions[0] / "bin" / f"{name}.exe") if versions else None


def main():
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        sys.exit("Falta DATABASE_URL en .env.")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql":
        sys.exit("El respaldo requiere una DATABASE_URL PostgreSQL.")
    executable = pg_tool("pg_dump")
    if not executable:
        sys.exit("No encuentro pg_dump. Agrega la carpeta bin de PostgreSQL al PATH o define POSTGRES_BIN.")
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    target = backup_dir / f"{url.database}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dump"
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    args = [executable, "--format=custom", "--no-owner", "--host", url.host or "127.0.0.1", "--port", str(url.port or 5432), "--username", url.username or "postgres", "--dbname", url.database, "--file", str(target)]
    result = subprocess.run(args, env=env, check=False)
    env.pop("PGPASSWORD", None)
    if result.returncode:
        target.unlink(missing_ok=True)
        sys.exit(f"pg_dump falló (código {result.returncode}); revisa PostgreSQL y DATABASE_URL.")
    print(f"Respaldo creado: {target}")


if __name__ == "__main__":
    main()
