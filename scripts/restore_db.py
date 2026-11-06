"""Restauración PostgreSQL con confirmación explícita y destino local solamente."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def pg_tool():
    found = shutil.which("pg_restore")
    if found:
        return found
    bin_override = os.environ.get("POSTGRES_BIN")
    if bin_override and (Path(bin_override) / "pg_restore.exe").exists():
        return str(Path(bin_override) / "pg_restore.exe")
    base = Path(r"C:\Program Files\PostgreSQL")
    versions = sorted((p for p in base.glob("*") if (p / "bin" / "pg_restore.exe").exists()), reverse=True)
    return str(versions[0] / "bin" / "pg_restore.exe") if versions else None


def main():
    if len(sys.argv) != 2:
        sys.exit(r"Uso: python scripts/restore_db.py backups\oficiosya_YYYYMMDD_HHMMSS.dump")
    backup = Path(sys.argv[1]).resolve()
    if not backup.is_file() or backup.suffix.lower() != ".dump":
        sys.exit("Indica un archivo de respaldo .dump existente.")
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        sys.exit("Falta DATABASE_URL en .env.")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or (url.host or "").lower() not in ("localhost", "127.0.0.1", "::1"):
        sys.exit("Por seguridad, este script restaura solo en PostgreSQL local.")
    executable = pg_tool()
    if not executable:
        sys.exit("No encuentro pg_restore. Agrega la carpeta bin de PostgreSQL al PATH o define POSTGRES_BIN.")
    print(f"Destino local: base {url.database} en {url.host}:{url.port or 5432}.")
    if input("La restauración reemplaza objetos del destino. Escribe RESTAURAR para continuar: ").strip() != "RESTAURAR":
        sys.exit("Restauración cancelada.")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    args = [executable, "--clean", "--if-exists", "--no-owner", "--exit-on-error", "--host", url.host, "--port", str(url.port or 5432), "--username", url.username or "postgres", "--dbname", url.database, str(backup)]
    result = subprocess.run(args, env=env, check=False)
    env.pop("PGPASSWORD", None)
    if result.returncode:
        sys.exit(f"pg_restore falló (código {result.returncode}); revisa el respaldo y la conexión.")
    print("Restauración completada.")


if __name__ == "__main__":
    main()
