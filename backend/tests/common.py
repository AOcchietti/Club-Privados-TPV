"""Utilidades comunes de las pruebas: arranca server.py sobre la base de datos en memoria."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# TPV_BACKEND_DIR permite probar otra copia del backend (lo usa test_mutations.py)
BACKEND = os.environ.get("TPV_BACKEND_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
import stubs  # noqa: E402,F401  (instala los sustitutos antes de importar el servidor)

os.environ.update(
    MONGO_URL="mongodb://memoria",
    DB_NAME="pruebas",
    JWT_SECRET="clave-de-pruebas-suficientemente-larga-1234567890",
    COOKIE_SECURE="false",
    LOCAL_STORAGE_DIR=tempfile.mkdtemp(prefix="tpv-pruebas-"),
)
os.environ.pop("EMERGENT_LLM_KEY", None)
os.environ.pop("ADMIN_RESET_PASSWORD", None)
sys.path.insert(0, BACKEND)

import server as S  # noqa: E402

HTTPException = stubs.HTTPException


class Checker:
    def __init__(self, name):
        self.name = name
        self.passed = 0

    def __call__(self, cond, msg):
        if not cond:
            raise AssertionError(f"[{self.name}] {msg}")
        self.passed += 1

    async def error(self, coro, status=None, contains=None):
        try:
            await coro
        except HTTPException as e:
            if status is not None:
                self(e.status_code == status, f"esperaba {status}, llegó {e.status_code}: {e.detail}")
            if contains:
                self(contains.lower() in str(e.detail).lower(), f"esperaba '{contains}' en '{e.detail}'")
            return e
        raise AssertionError(f"[{self.name}] esperaba un error {status or ''} {contains or ''}")

    def done(self):
        print(f"OK · {self.name}: {self.passed} comprobaciones")


async def as_user(email):
    u = await S.db.users.find_one({"email": email})
    u["id"] = str(u.pop("_id"))
    return u


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
