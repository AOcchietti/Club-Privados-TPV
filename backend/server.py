from dotenv import load_dotenv
import asyncio
import hashlib
import secrets
import smtplib
import ssl
from contextlib import asynccontextmanager
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
load_dotenv()

import io
import mimetypes
import os
import re
import logging
import uuid
import unicodedata
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Optional, List
from zoneinfo import ZoneInfo

import bcrypt
import jwt
import requests
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Query, UploadFile, File
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from cierre_pdf import build_closing_pdf, as_local
from demo_catalog import FOOD_DRINK_CATEGORIES, FOOD_DRINK_PRODUCTS

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

@asynccontextmanager
async def lifespan(_app):
    """Arranque y parada del servidor. Starlette 1.x eliminó @app.on_event: se usa lifespan."""
    await startup()
    yield
    client.close()


app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")

APP_VERSION = "1.0.0"
JWT_ALGORITHM = "HS256"
MADRID = ZoneInfo("Europe/Madrid")
STAFF_ROLES = ["admin", "cajero"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("weedlemon")


# ---------- helpers ----------

# bcrypt solo usa los primeros 72 bytes. Hasta bcrypt 4 el resto se ignoraba en silencio; bcrypt 5 da error.
# Se recorta siempre igual para que las contraseñas ya guardadas sigan funcionando con cualquier versión.
BCRYPT_MAX_BYTES = 72


def _pw_bytes(password: str) -> bytes:
    return (password or "").encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str):
    if len(password or "") < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    if len((password or "").encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="La contraseña no puede superar 72 caracteres")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(plain), hashed.encode("utf-8"))
    except Exception:
        return False


# "pwv" = versión de la contraseña: al restablecerla (o si un admin la cambia) sube y todas las sesiones anteriores caducan.
def create_access_token(user_id: str, email: str, role: str, pwv: int = 0) -> str:
    payload = {"sub": user_id, "email": email, "role": role, "type": "access", "jti": uuid.uuid4().hex, "pwv": pwv,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=60 * 8)}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, pwv: int = 0) -> str:
    payload = {"sub": user_id, "type": "refresh", "jti": uuid.uuid4().hex, "pwv": pwv,
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


# En producción (https) las cookies van Secure + SameSite=None. En local (http://localhost)
# se pone COOKIE_SECURE=false en el .env y pasan a SameSite=Lax.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").strip().lower() not in ("false", "0", "no")
# Si la app y la API se sirven desde la misma web (Dockerfile), COOKIE_SAMESITE=lax es más seguro.
COOKIE_SAMESITE = (os.environ.get("COOKIE_SAMESITE") or "").strip().lower()
if COOKIE_SAMESITE not in ("lax", "strict", "none") or (COOKIE_SAMESITE == "none" and not COOKIE_SECURE):
    COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"


def set_access_cookie(response: Response, access: str):
    response.set_cookie("access_token", access, httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
                        max_age=60 * 60 * 8, path="/")


def set_auth_cookies(response: Response, access: str, refresh: str):
    set_access_cookie(response, access)
    response.set_cookie("refresh_token", refresh, httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
                        max_age=604800, path="/")


def ser(doc):
    if not doc:
        return None
    d = dict(doc)
    if "_id" in d:  # el usuario de la sesión ya llega con "id" (get_current_user quita el _id)
        d["id"] = str(d.pop("_id"))
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, ObjectId):
            d[k] = str(v)
    d.pop("password_hash", None)
    return d


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_aware(value):
    """MongoDB devuelve las fechas sin zona horaria (en UTC): se marcan como UTC para poder compararlas."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def log_activity(actor: dict, action: str, details: str):
    await db.activity.insert_one({
        "user_id": actor.get("id") or actor.get("_id"),
        "user_name": actor.get("name", "Sistema"),
        "user_role": actor.get("role", "-"),
        "action": action,
        "details": details,
        "created_at": now_utc(),
    })


async def is_revoked(payload: dict) -> bool:
    return bool(payload.get("jti")) and await db.revoked_tokens.find_one({"jti": payload["jti"]}) is not None


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Token inválido")
        if await is_revoked(payload):  # sesión cerrada: el token copiado ya no sirve
            raise HTTPException(status_code=401, detail="Sesión cerrada")
        try:
            uid = ObjectId(payload.get("sub"))
        except (InvalidId, TypeError):
            raise HTTPException(status_code=401, detail="Token inválido")
        user = await db.users.find_one({"_id": uid})
        if not user:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        # Una cuenta suspendida, pendiente o que ya no es del equipo pierde el acceso al momento,
        # aunque todavía tenga un token sin caducar.
        if user.get("role") not in STAFF_ROLES or user.get("status") in ("suspendida", "pendiente"):
            raise HTTPException(status_code=401, detail="Cuenta sin acceso")
        if payload.get("pwv", 0) != user.get("pw_version", 0):
            raise HTTPException(status_code=401, detail="La contraseña ha cambiado: vuelve a entrar")
        user["id"] = str(user.pop("_id"))
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesión expirada")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


def require_roles(*roles):
    async def checker(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Sin permisos suficientes")
        return user
    return checker


require_staff = require_roles("admin", "cajero")
require_admin = require_roles("admin")


async def next_seq(name: str) -> int:
    doc = await db.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return doc["seq"]


# Un único turno activo por local: "opening" (recuento de apertura), "open" (vendiendo)
# y "closing" (arqueo + recuento de cierre). "closed" y "cancelled" son estados finales.
ACTIVE_STATUSES = ["opening", "open", "closing"]
STATUS_TEXT = {"opening": "en apertura (recuento de stock)", "open": "abierta", "closing": "en proceso de cierre"}
USER_STATUSES = ["activa", "pendiente", "expirada", "suspendida"]
MAX_QTY = 1_000_000  # tope de cordura para cantidades de stock


def is_whole(qty: float) -> bool:
    return abs(qty - round(qty)) < 1e-9


def require_whole_units(product: dict, qty: float):
    """Los productos por unidades (latas, chocolatinas, accesorios…) no se fraccionan."""
    if product.get("unit") == "ud" and not is_whole(qty):
        raise HTTPException(status_code=400, detail=f"«{product['name']}» va por unidades: la cantidad tiene que ser un número entero")
DOC_TYPES = ["DNI", "NIE", "Pasaporte", "Otro"]


async def get_active_session():
    return await db.cash_sessions.find_one({"status": {"$in": ACTIVE_STATUSES}})


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Elemento no encontrado")


def client_ip(request: Request) -> str:
    # La primera entrada de X-Forwarded-For la puede escribir el propio cliente (y saltarse los
    # límites de intentos); la última la añade el proxy que tenemos delante.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        last = fwd.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "desconocida"


async def rate_limit(request: Request, bucket: str, limit: int, minutes: int = 60):
    ip = client_ip(request)
    since = now_utc() - timedelta(minutes=minutes)
    hits = await db.public_hits.count_documents({"bucket": bucket, "ip": ip, "at": {"$gte": since}})
    if hits >= limit:
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes desde esta conexión. Inténtalo más tarde.")
    await db.public_hits.insert_one({"bucket": bucket, "ip": ip, "at": now_utc()})


def norm_doc(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return re.sub(r"[\s\-\.]", "", value).upper() or None


def day_bounds_madrid(day: datetime):
    local = day.astimezone(MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    start = local.astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start, end


STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "weedlemon"
storage_key = None


def init_storage(force: bool = False):
    global storage_key
    if storage_key and not force:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key


# Dónde se guardan fotos y PDF (FILE_STORAGE):
#   local    → en disco, en backend/uploads/ o en LOCAL_STORAGE_DIR (por defecto sin EMERGENT_LLM_KEY)
#   mongo    → dentro de MongoDB (colección file_blobs). Para servidores sin disco permanente (Render, Railway…)
#   emergent → almacenamiento de Emergent (por defecto si hay EMERGENT_LLM_KEY)
STORAGE_MODE = (os.environ.get("FILE_STORAGE") or "").strip().lower()
if STORAGE_MODE not in ("local", "mongo", "emergent"):
    STORAGE_MODE = "emergent" if (os.environ.get("EMERGENT_LLM_KEY") or "").strip() else "local"
LOCAL_STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR") or Path(__file__).parent / "uploads").resolve()


def local_path(path: str) -> Path:
    target = (LOCAL_STORAGE_DIR / path).resolve()
    if LOCAL_STORAGE_DIR not in target.parents:
        raise HTTPException(status_code=400, detail="Ruta de archivo no válida")
    return target


def _emergent_put(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _emergent_get(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


async def put_object(path: str, data: bytes, content_type: str) -> dict:
    if STORAGE_MODE == "local":
        target = local_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": path, "size": len(data)}
    if STORAGE_MODE == "mongo":  # cada archivo es un documento (las subidas tienen tope de 10 MB < 16 MB de MongoDB)
        await db.file_blobs.update_one({"path": path}, {"$set": {"path": path, "data": data, "content_type": content_type,
                                                                 "size": len(data), "created_at": now_utc()}}, upsert=True)
        return {"path": path, "size": len(data)}
    return await asyncio.to_thread(_emergent_put, path, data, content_type)


async def get_object(path: str):
    if STORAGE_MODE == "local":
        target = local_path(path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if STORAGE_MODE == "mongo":
        blob = await db.file_blobs.find_one({"path": path})
        if not blob:
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        return bytes(blob["data"]), blob.get("content_type") or "application/octet-stream"
    return await asyncio.to_thread(_emergent_get, path)


# ---------- correo ----------
# Proveedor según las variables de entorno (el primero que esté configurado):
#   BREVO_API_KEY → API HTTPS de Brevo (funciona aunque el hosting bloquee SMTP, como el plan gratis de Render)
#   SMTP_HOST     → cualquier servidor SMTP (Gmail con contraseña de aplicación, el correo de tu dominio…)
#   ninguno       → en local el correo se muestra en la consola del backend; en producción se avisa del error
# Remitente: EMAIL_FROM (dirección) y EMAIL_FROM_NAME.
BACKGROUND_TASKS = set()


def run_in_background(coro):
    """Lanza una tarea sin esperarla (la respuesta no tarda más si hay que enviar un correo)."""
    task = asyncio.get_running_loop().create_task(coro)
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return task


def email_provider() -> Optional[str]:
    if (os.environ.get("BREVO_API_KEY") or "").strip():
        return "brevo"
    if (os.environ.get("SMTP_HOST") or "").strip():
        return "smtp"
    return None


def email_sender():
    address = (os.environ.get("EMAIL_FROM") or os.environ.get("SMTP_USER") or "no-reply@localhost").strip()
    return (os.environ.get("EMAIL_FROM_NAME") or "Weed Lemon Social Club").strip(), address


def _send_smtp(to: str, subject: str, text: str, html: Optional[str]):
    name, address = email_sender()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((name, address))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=address.split("@")[-1] or None)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT") or 587)
    security = (os.environ.get("SMTP_SECURITY") or ("ssl" if port == 465 else "starttls")).strip().lower()
    context = ssl.create_default_context()
    server = smtplib.SMTP_SSL(host, port, timeout=20, context=context) if security == "ssl" else smtplib.SMTP(host, port, timeout=20)
    with server:
        if security == "starttls":
            server.starttls(context=context)
        if os.environ.get("SMTP_USER"):
            server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        server.send_message(msg)


def _send_brevo(to: str, subject: str, text: str, html: Optional[str]):
    name, address = email_sender()
    resp = requests.post("https://api.brevo.com/v3/smtp/email", timeout=20,
                         headers={"api-key": os.environ["BREVO_API_KEY"].strip(), "content-type": "application/json", "accept": "application/json"},
                         json={"sender": {"name": name, "email": address}, "to": [{"email": to}], "subject": subject,
                               "textContent": text, "htmlContent": html or f"<pre>{text}</pre>"})
    if resp.status_code >= 300:
        raise RuntimeError(f"Brevo respondió {resp.status_code}: {resp.text[:200]}")


async def send_email(to: str, subject: str, text: str, html: Optional[str] = None) -> bool:
    provider = email_provider()
    if not provider:
        if COOKIE_SECURE:
            logger.error("Correo sin configurar (BREVO_API_KEY o SMTP_HOST): no se ha enviado «%s» a %s", subject, to)
        else:  # en local: se ve en la consola para poder probar sin servidor de correo
            logger.warning("Correo sin configurar; en local se muestra aquí.\nPara: %s\nAsunto: %s\n%s", to, subject, text)
        return False
    try:
        await asyncio.to_thread(_send_brevo if provider == "brevo" else _send_smtp, to, subject, text, html)
        logger.info("Correo «%s» enviado a %s (%s)", subject, to, provider)
        return True
    except Exception as e:  # noqa: BLE001 — un fallo de correo nunca rompe la petición
        logger.error("No se pudo enviar «%s» a %s por %s: %s", subject, to, provider, e)
        return False


def public_app_url() -> str:
    """Dirección pública de la app para los enlaces de los correos. Sale de la configuración, nunca de la petición
    (si se usara la cabecera Host, alguien podría hacer que el enlace apuntara a su web)."""
    return (os.environ.get("FRONTEND_URL") or "http://localhost:3000").strip().rstrip("/")


def _email_html(title: str, paragraphs: List[str], button: Optional[tuple] = None) -> str:
    import html as _h
    body = "".join(f"<p style='margin:0 0 14px'>{_h.escape(p)}</p>" for p in paragraphs)
    if button:
        label, url = button
        body += (f"<p style='margin:22px 0'><a href='{_h.escape(url)}' style='background:#facc15;color:#0f172a;padding:12px 20px;"
                 f"border-radius:10px;text-decoration:none;font-weight:700'>{_h.escape(label)}</a></p>"
                 f"<p style='margin:0 0 14px;font-size:12px;color:#64748b'>Si el botón no funciona, copia este enlace:<br>{_h.escape(url)}</p>")
    return (f"<div style='font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#0f172a'>"
            f"<p style='font-size:12px;font-weight:700;letter-spacing:.08em;color:#a16207'>WEED LEMON SOCIAL CLUB</p>"
            f"<h2 style='margin:0 0 16px'>{_h.escape(title)}</h2>{body}</div>")


# ---------- schemas ----------

class LoginIn(BaseModel):
    email: str
    password: str


# Datos de identificación (KYC) del socio. Las fotos y la firma son rutas del object storage.
SOCIO_FIELDS = ["apellidos", "doc_type", "doc_number", "nationality", "birthdate",
                "doc_photo", "face_photo", "signature"]


class UserCreate(BaseModel):
    name: str
    role: str = "socio"
    email: Optional[str] = None
    password: Optional[str] = None
    dni: Optional[str] = None
    phone: Optional[str] = None
    status: str = "activa"
    apellidos: Optional[str] = None
    doc_type: Optional[str] = None
    doc_number: Optional[str] = None
    nationality: Optional[str] = None
    birthdate: Optional[str] = None
    doc_photo: Optional[str] = None
    face_photo: Optional[str] = None
    signature: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    dni: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    apellidos: Optional[str] = None
    doc_type: Optional[str] = None
    doc_number: Optional[str] = None
    nationality: Optional[str] = None
    birthdate: Optional[str] = None
    doc_photo: Optional[str] = None
    face_photo: Optional[str] = None
    signature: Optional[str] = None


class PublicAltaIn(BaseModel):
    name: str
    apellidos: str
    doc_type: str = "DNI"
    doc_number: str
    nationality: str
    birthdate: str
    phone: str
    email: Optional[str] = None
    doc_photo: str
    face_photo: str
    signature: str
    legal_accepted: bool = False


class ProductBase(BaseModel):
    name: str
    category: str
    price: float
    thc: Optional[float] = None
    cbd: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    active: bool = True


class ProductCreate(ProductBase):
    unit: str = "g"
    initial_stock: float = 0


class ProductUpdate(ProductBase):
    """El stock y la unidad no se editan aquí: el stock va por movimientos de inventario."""


class StockMoveIn(BaseModel):
    type: str  # "entrada" | "merma" | "ajuste"
    qty: float  # entrada/merma: cantidad positiva · ajuste: diferencia con signo (real − sistema)
    reason: str


class SaleItemIn(BaseModel):
    product_id: str
    qty: float


class SaleCreate(BaseModel):
    items: List[SaleItemIn]
    payment_method: str = "saldo"
    socio_id: Optional[str] = None


class CashOpenIn(BaseModel):
    starting_amount: float = 0


class ClosingCashIn(BaseModel):
    counted: Optional[float] = None
    reason: Optional[str] = None


class StocktakeLineIn(BaseModel):
    product_id: str
    counted: Optional[float] = None
    version: int


class AutofillIn(BaseModel):
    section: Optional[str] = None
    product_id: Optional[str] = None
    all: bool = False            # todo el recuento de una vez
    only_pending: bool = False   # no tocar lo que ya se ha contado
    version: int


class CashMovementIn(BaseModel):
    type: str  # "in" | "out"
    amount: float
    reason: str


# ---------- auth ----------

@api_router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    email = body.email.strip().lower()
    identifier = f"{client_ip(request)}:{email}"
    attempt = await db.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("count", 0) >= 5:
        locked_until = as_aware(attempt.get("locked_until"))
        if locked_until and locked_until > now_utc():
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera 15 minutos.")
    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(body.password, user["password_hash"]):
        await db.login_attempts.update_one(
            {"identifier": identifier},
            {"$inc": {"count": 1}, "$set": {"locked_until": now_utc() + timedelta(minutes=15)}},
            upsert=True)
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    if user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Este acceso es solo para el equipo del club")
    if user.get("status") == "suspendida":
        raise HTTPException(status_code=403, detail="Cuenta suspendida")
    if user.get("status") == "pendiente":
        raise HTTPException(status_code=403, detail="Cuenta pendiente de activación")
    await db.login_attempts.delete_one({"identifier": identifier})
    access = create_access_token(str(user["_id"]), email, user["role"], user.get("pw_version", 0))
    refresh = create_refresh_token(str(user["_id"]), user.get("pw_version", 0))
    set_auth_cookies(response, access, refresh)
    out = ser(user)  # el token solo viaja en la cookie httpOnly: no queda al alcance de JavaScript
    await log_activity(out, "login", f"{out['name']} inició sesión")
    return out


async def revoke_token(token: Optional[str]) -> Optional[dict]:
    """Anula un token hasta que caduque (aunque alguien lo hubiera copiado)."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM], options={"verify_exp": False})
    except jwt.InvalidTokenError:
        return None
    if payload.get("jti"):
        expires = datetime.fromtimestamp(payload.get("exp") or 0, timezone.utc)
        await db.revoked_tokens.update_one({"jti": payload["jti"]}, {"$set": {"jti": payload["jti"], "expires_at": expires}}, upsert=True)
    return payload


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    # No exige sesión válida: también se puede cerrar con el token de acceso ya caducado.
    access = await revoke_token(request.cookies.get("access_token"))
    await revoke_token(request.cookies.get("refresh_token"))
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    user = None
    if access and access.get("type") == "access":
        try:
            user = await db.users.find_one({"_id": ObjectId(access.get("sub"))})
        except (InvalidId, TypeError):
            user = None
    if user:
        actor = ser(user)
        await log_activity(actor, "logout", f"{actor['name']} cerró sesión")
    return {"ok": True}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return ser(user)


@api_router.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")
    if await is_revoked(payload):
        raise HTTPException(status_code=401, detail="Sesión cerrada")
    try:
        user = await db.users.find_one({"_id": ObjectId(payload.get("sub"))})
    except (InvalidId, TypeError):
        user = None
    if not user or user.get("role") not in STAFF_ROLES or user.get("status") in ("suspendida", "pendiente"):
        raise HTTPException(status_code=401, detail="Cuenta sin acceso")
    if payload.get("pwv", 0) != user.get("pw_version", 0):
        raise HTTPException(status_code=401, detail="La contraseña ha cambiado: vuelve a entrar")
    access = create_access_token(str(user["_id"]), user["email"], user["role"], user.get("pw_version", 0))
    set_access_cookie(response, access)
    return {"ok": True}


# ---------- recuperación de contraseña ----------
# 1) /auth/forgot-password: siempre responde lo mismo (no revela si el email existe). Si es una cuenta del equipo,
#    crea un enlace de un solo uso que caduca en 30 minutos y lo envía por correo. Solo se guarda el hash del token.
# 2) /auth/reset-password: con ese token se pone una contraseña nueva; todas las sesiones anteriores caducan
#    y se avisa por correo del cambio.
RESET_MINUTES = 30
RESET_MAX_PER_HOUR = 3
RESET_INVALID = "El enlace no es válido o ha caducado. Pide uno nuevo desde «¿Has olvidado tu contraseña?»."
FORGOT_RESPONSE = {"ok": True, "message": "Si ese email es de una cuenta del equipo, te hemos enviado un enlace para cambiar la "
                                          f"contraseña. Caduca en {RESET_MINUTES} minutos; revisa también la carpeta de spam."}


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str


def reset_token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


async def send_reset_email(user: dict, link: str):
    name = (user.get("name") or "").split(" ")[0] or "hola"
    text = (f"Hola {name}:\n\nAlguien (seguramente tú) ha pedido cambiar la contraseña de tu cuenta del TPV.\n\n"
            f"Abre este enlace para elegir una nueva. Caduca en {RESET_MINUTES} minutos y solo sirve una vez:\n{link}\n\n"
            "Si no lo has pedido tú, ignora este correo: tu contraseña no cambia.")
    html = _email_html("Cambia tu contraseña", [
        f"Hola {name}:", "Alguien (seguramente tú) ha pedido cambiar la contraseña de tu cuenta del TPV.",
        f"El enlace caduca en {RESET_MINUTES} minutos y solo sirve una vez."], ("Elegir contraseña nueva", link))
    html += "<p style='font-family:Arial,sans-serif;max-width:520px;margin:auto;font-size:12px;color:#64748b'>Si no lo has pedido tú, ignora este correo: tu contraseña no cambia.</p>"
    await send_email(user["email"], "Cambia tu contraseña del TPV", text, html)


async def send_password_changed_email(user: dict):
    text = ("Hola:\n\nLa contraseña de tu cuenta del TPV se acaba de cambiar y se han cerrado las sesiones abiertas.\n\n"
            "Si no has sido tú, avisa cuanto antes a un administrador del club.")
    await send_email(user["email"], "Tu contraseña del TPV se ha cambiado", text,
                     _email_html("Contraseña cambiada", ["La contraseña de tu cuenta del TPV se acaba de cambiar y se han cerrado las sesiones abiertas.",
                                                         "Si no has sido tú, avisa cuanto antes a un administrador del club."]))


@api_router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordIn, request: Request):
    await rate_limit(request, "forgot_password", limit=10)
    email = (body.email or "").strip().lower()
    if not email or len(email) > 254:
        return FORGOT_RESPONSE
    user = await db.users.find_one({"email": email})
    if not user or user.get("role") not in STAFF_ROLES or user.get("status") in ("suspendida", "pendiente"):
        return FORGOT_RESPONSE
    uid = str(user["_id"])
    recent = await db.password_resets.count_documents({"user_id": uid, "created_at": {"$gte": now_utc() - timedelta(hours=1)}})
    if recent >= RESET_MAX_PER_HOUR:  # nadie puede llenar el buzón de otra persona
        return FORGOT_RESPONSE
    await db.password_resets.update_many({"user_id": uid, "used_at": None}, {"$set": {"used_at": now_utc(), "superseded": True}})
    token = secrets.token_urlsafe(32)
    await db.password_resets.insert_one({"user_id": uid, "token_hash": reset_token_hash(token), "created_at": now_utc(),
                                         "expires_at": now_utc() + timedelta(minutes=RESET_MINUTES), "used_at": None,
                                         "ip": client_ip(request)})
    run_in_background(send_reset_email(user, f"{public_app_url()}/restablecer?token={token}"))
    await log_activity(ser(user), "password_reset_pedido", f"Enlace para cambiar la contraseña enviado a {email}")
    return FORGOT_RESPONSE


@api_router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordIn, request: Request):
    await rate_limit(request, "reset_password", limit=20)
    rec = await db.password_resets.find_one({"token_hash": reset_token_hash(body.token), "used_at": None})
    if not rec or as_aware(rec["expires_at"]) <= now_utc():
        raise HTTPException(status_code=400, detail=RESET_INVALID)
    check_password(body.password)
    user = await db.users.find_one({"_id": oid(rec["user_id"])})
    if not user or user.get("role") not in STAFF_ROLES or user.get("status") in ("suspendida", "pendiente"):
        raise HTTPException(status_code=400, detail=RESET_INVALID)
    # Un solo uso, también si llegan dos peticiones a la vez con el mismo enlace
    res = await db.password_resets.update_one({"_id": rec["_id"], "used_at": None}, {"$set": {"used_at": now_utc()}})
    if res.modified_count == 0:
        raise HTTPException(status_code=400, detail=RESET_INVALID)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.password)},
                                                     "$inc": {"pw_version": 1}})  # cierra todas las sesiones anteriores
    await db.password_resets.update_many({"user_id": rec["user_id"], "used_at": None}, {"$set": {"used_at": now_utc()}})
    await db.login_attempts.delete_many({"identifier": {"$regex": re.escape(":" + user["email"]) + "$"}})
    await log_activity(ser(user), "password_restablecida", f"{user['name']} cambió su contraseña con el enlace del correo")
    run_in_background(send_password_changed_email(user))
    return {"ok": True}


# ---------- users (equipo + socios) ----------

@api_router.get("/users")
async def list_users(role: Optional[str] = None, q: Optional[str] = None, user: dict = Depends(require_staff)):
    query = {}
    if user["role"] != "admin":
        query["role"] = "socio"
    elif role:
        query["role"] = role
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"name": rx}, {"apellidos": rx}, {"dni": rx}, {"doc_number": rx},
                        {"member_number": rx}, {"email": rx}]
    docs = await db.users.find(query).sort("created_at", -1).to_list(1000)
    return [ser(d) for d in docs]


async def assign_member_number(doc: dict):
    """Todo usuario (socio o equipo) tiene nº de socio y saldo propio."""
    n = await next_seq("member")
    doc["member_number"] = f"WL-{n:04d}"
    doc["balance"] = 0.0


async def ensure_unique_doc(doc_number: Optional[str], exclude_id: Optional[ObjectId] = None):
    if not doc_number:
        return
    query = {"$or": [{"doc_number": doc_number}, {"dni": doc_number}]}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    if await db.users.find_one(query):
        raise HTTPException(status_code=400, detail="Ya existe un socio o una solicitud con ese documento")


def clean_socio_fields(data: dict) -> dict:
    out = {}
    for k in SOCIO_FIELDS:
        if k in data:
            v = data[k]
            out[k] = v.strip() if isinstance(v, str) else v
    if "doc_number" in out:
        out["doc_number"] = norm_doc(out["doc_number"])
    if out.get("doc_type") and out["doc_type"] not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de documento no válido")
    return out


@api_router.post("/users")
async def create_user(body: UserCreate, user: dict = Depends(require_staff)):
    if body.role not in ["admin", "cajero", "socio"]:
        raise HTTPException(status_code=400, detail="Rol no válido")
    if user["role"] != "admin" and body.role != "socio":
        raise HTTPException(status_code=403, detail="Solo el administrador puede crear miembros del equipo")
    if body.status not in USER_STATUSES:
        raise HTTPException(status_code=400, detail="Estado no válido")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    doc = {
        "name": body.name.strip(),
        "role": body.role,
        "email": body.email.strip().lower() if body.email else None,
        "phone": body.phone,
        "status": body.status,
        "created_at": now_utc(),
        "created_by": user["name"],
    }
    if body.role in STAFF_ROLES:
        if not doc["email"] or not body.password:
            raise HTTPException(status_code=400, detail="Email y contraseña obligatorios para el equipo")
        if await db.users.find_one({"email": doc["email"]}):
            raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email")
        check_password(body.password)
        doc["password_hash"] = hash_password(body.password)
    if body.role == "socio":
        doc.update(clean_socio_fields(body.model_dump()))
        if body.dni and not doc.get("doc_number"):
            doc["doc_number"] = norm_doc(body.dni)
            doc["doc_type"] = doc.get("doc_type") or "DNI"
        await ensure_unique_doc(doc.get("doc_number"))
        if doc["email"] and await db.users.find_one({"email": doc["email"], "role": {"$ne": "socio"}}):
            raise HTTPException(status_code=400, detail="Ese email pertenece a un miembro del equipo")
    await assign_member_number(doc)
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "usuario_creado", f"Alta de {body.role} «{doc['name']}» ({doc['member_number']})")
    return ser(doc)


@api_router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, user: dict = Depends(require_staff)):
    target = await db.users.find_one({"_id": oid(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user["role"] != "admin" and target.get("role") != "socio":
        raise HTTPException(status_code=403, detail="Solo el administrador puede editar el equipo")
    updates = {}
    data = body.model_dump(exclude_none=True)
    for k in ["name", "dni", "phone"]:
        if k in data:
            updates[k] = data[k]
    if "status" in data:
        if data["status"] not in USER_STATUSES:
            raise HTTPException(status_code=400, detail="Estado no válido")
        updates["status"] = data["status"]
    socio_updates = clean_socio_fields(data)
    if socio_updates.get("doc_number") and socio_updates["doc_number"] != target.get("doc_number"):
        await ensure_unique_doc(socio_updates["doc_number"], exclude_id=target["_id"])
    updates.update(socio_updates)
    if "email" in data and data["email"]:
        updates["email"] = data["email"].strip().lower()
    if user["role"] == "admin":
        if "role" in data and data["role"] != target.get("role"):
            if data["role"] not in ["admin", "cajero", "socio"]:
                raise HTTPException(status_code=400, detail="Rol no válido")
            if data["role"] in STAFF_ROLES and not target.get("password_hash") and not data.get("password"):
                raise HTTPException(status_code=400, detail="Para pasar a equipo hace falta email y contraseña")
            updates["role"] = data["role"]
        if "password" in data and data["password"]:
            check_password(data["password"])
            updates["password_hash"] = hash_password(data["password"])
    if not updates:
        return ser(target)
    change = {"$set": updates}
    if "password_hash" in updates and str(target["_id"]) != user["id"]:
        change["$inc"] = {"pw_version": 1}  # sus sesiones abiertas dejan de valer
    await db.users.update_one({"_id": ObjectId(user_id)}, change)
    await log_activity(user, "usuario_editado", f"Editado «{target['name']}»: {', '.join(updates.keys())}")
    return ser(await db.users.find_one({"_id": ObjectId(user_id)}))


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    target = await db.users.find_one({"_id": oid(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if abs(target.get("balance") or 0) > 0.005:
        raise HTTPException(status_code=400, detail=f"No se puede eliminar: tiene un saldo de {round(target['balance'], 2)} Cr. Déjalo a 0 o suspende la cuenta.")
    await db.users.delete_one({"_id": target["_id"]})
    await log_activity(user, "usuario_eliminado", f"Baja de {target.get('role')} «{target['name']}»")
    return {"ok": True}


class RechargeIn(BaseModel):
    amount: float
    method: str = "efectivo"


@api_router.get("/users/{user_id}")
async def get_user(user_id: str, user: dict = Depends(require_staff)):
    doc = await db.users.find_one({"_id": oid(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return ser(doc)


@api_router.post("/users/{user_id}/recharge")
async def recharge_balance(user_id: str, body: RechargeIn, user: dict = Depends(require_staff)):
    target = await db.users.find_one({"_id": oid(user_id), "member_number": {"$exists": True}})
    if not target:
        raise HTTPException(status_code=404, detail="Socio no encontrado")
    if body.amount <= 0 or body.amount > 1000:
        raise HTTPException(status_code=400, detail="Importe no válido (máx. 1000 Cr por recarga)")
    if body.method != "efectivo":
        raise HTTPException(status_code=400, detail="Las recargas solo se hacen en efectivo")
    session = await get_active_session()
    if session and session["status"] != "open":
        raise HTTPException(status_code=400, detail=f"La caja está {STATUS_TEXT[session['status']]}: las recargas están en pausa")
    # Sin turno abierto la recarga queda "fuera de turno": el saldo sube ya y el efectivo
    # se incorpora al esperado del siguiente turno cuando se abra (igual que las ventas).
    out_of_shift = session is None
    amount = round(body.amount, 2)
    await db.users.update_one({"_id": target["_id"]}, {"$inc": {"balance": amount}})
    await db.recharges.insert_one({
        "socio_id": user_id,
        "socio_name": target["name"],
        "amount": amount,
        "method": "efectivo",
        "session_id": None if out_of_shift else str(session["_id"]),
        "out_of_shift": out_of_shift,
        "out_of_shift_pending": out_of_shift,
        "created_by": user["name"],
        "created_at": now_utc(),
    })
    nota = " · FUERA DE TURNO (se incorporará a la próxima caja)" if out_of_shift else ""
    await log_activity(user, "recarga", f"Recarga de {amount} Cr (efectivo) para {target['name']}{nota}")
    out = ser(await db.users.find_one({"_id": target["_id"]}))
    out["recharge_out_of_shift"] = out_of_shift
    return out


@api_router.get("/users/{user_id}/recharges")
async def list_recharges(user_id: str, user: dict = Depends(require_staff)):
    docs = await db.recharges.find({"socio_id": user_id}).sort("created_at", -1).to_list(200)
    return [ser(d) for d in docs]


# ---------- uploads (object storage) ----------

def file_ext(filename: Optional[str], content_type: str, default: str) -> str:
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{1,5}", ext):
            return ext
    guessed = (content_type or "").split("/")[-1].lower()
    return guessed if re.fullmatch(r"[a-z0-9]{1,5}", guessed) else default


async def store_file(data: bytes, content_type: str, filename: Optional[str], folder: str,
                     created_by: str, public: bool = False) -> str:
    path = f"{APP_NAME}/{folder}/{uuid.uuid4()}.{file_ext(filename, content_type, 'bin')}"
    result = await put_object(path, data, content_type)
    await db.files.insert_one({
        "storage_path": result["path"],
        "original_filename": filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "is_deleted": False,
        "public_upload": public,
        "created_by": created_by,
        "created_at": now_utc(),
    })
    return result["path"]


IMAGE_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def sniff_image(data: bytes) -> Optional[str]:
    """Tipo real de la imagen según sus primeros bytes (no según lo que diga el navegador)."""
    for sig, ctype in IMAGE_SIGNATURES:
        if data.startswith(sig):
            return ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_limited(file: UploadFile, max_bytes: int, too_big: str) -> bytes:
    data = await file.read(max_bytes + 1)  # nunca se carga en memoria más de lo permitido
    if len(data) > max_bytes:
        raise HTTPException(status_code=400, detail=too_big)
    return data


async def read_image_upload(file: UploadFile, max_mb: int = 5):
    data = await read_limited(file, max_mb * 1024 * 1024, f"La imagen no puede superar {max_mb} MB")
    ctype = sniff_image(data)
    if not ctype:
        # SVG, HTML disfrazado, etc.: se rechaza para evitar que un archivo subido ejecute código
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes JPG, PNG, WEBP o GIF")
    return data, ctype


@api_router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(require_staff)):
    data, ctype = await read_image_upload(file)
    path = await store_file(data, ctype, file.filename, f"uploads/{user['id']}", user["id"])
    await log_activity(user, "foto_subida", f"Foto subida: {file.filename}")
    return {"path": path}


# ---------- alta pública de socios (formulario QR, sin login) ----------

@api_router.post("/public/upload")
async def public_upload(request: Request, file: UploadFile = File(...)):
    await rate_limit(request, "public_upload", limit=120)
    data, ctype = await read_image_upload(file, max_mb=8)
    path = await store_file(data, ctype, file.filename, "kyc", "formulario_publico", public=True)
    return {"path": path}


def parse_birthdate(value: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha de nacimiento no válida")


def age_on(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


@api_router.post("/public/alta")
async def public_alta(body: PublicAltaIn, request: Request):
    await rate_limit(request, "public_alta", limit=30)
    required = {"name": "nombre", "apellidos": "apellidos", "doc_number": "nº de documento",
                "nationality": "nacionalidad", "birthdate": "fecha de nacimiento", "phone": "teléfono"}
    for field, label in required.items():
        if not (getattr(body, field) or "").strip():
            raise HTTPException(status_code=400, detail=f"Falta el campo: {label}")
    if body.doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de documento no válido")
    if not body.legal_accepted:
        raise HTTPException(status_code=400, detail="Debes aceptar el acuerdo legal del club")
    birth = parse_birthdate(body.birthdate)
    today = now_utc().astimezone(MADRID).date()
    if birth > today or age_on(birth, today) > 120:
        raise HTTPException(status_code=400, detail="Fecha de nacimiento no válida")
    if age_on(birth, today) < 18:
        raise HTTPException(status_code=400, detail="Hay que ser mayor de edad para hacerse socio")
    for field, label in [("doc_photo", "la foto del documento"), ("face_photo", "la foto facial"), ("signature", "la firma")]:
        path = getattr(body, field)
        if not path or not await db.files.find_one({"storage_path": path, "public_upload": True, "is_deleted": False}):
            raise HTTPException(status_code=400, detail=f"Falta {label}")
    doc_number = norm_doc(body.doc_number)
    await ensure_unique_doc(doc_number)
    email = body.email.strip().lower() if body.email and body.email.strip() else None
    legal = await db.settings.find_one({"key": "legal_pdf"})
    doc = {
        "name": body.name.strip(),
        "apellidos": body.apellidos.strip(),
        "doc_type": body.doc_type,
        "doc_number": doc_number,
        "nationality": body.nationality.strip(),
        "birthdate": birth.isoformat(),
        "phone": body.phone.strip(),
        "email": email,
        "doc_photo": body.doc_photo,
        "face_photo": body.face_photo,
        "signature": body.signature,
        "role": "socio",
        "status": "pendiente",
        "legal_accepted_at": now_utc(),
        "legal_version": legal["updated_at"].isoformat() if legal else None,
        "signup_source": "formulario_qr",
        "created_at": now_utc(),
        "created_by": "Formulario QR",
    }
    await assign_member_number(doc)
    await db.users.insert_one(doc)
    await log_activity({"name": "Formulario QR", "role": "público"}, "alta_publica",
                       f"Solicitud de alta de «{doc['name']} {doc['apellidos']}» ({doc['member_number']}) pendiente de activar")
    return {"name": doc["name"], "member_number": doc["member_number"]}


@api_router.get("/public/legal")
async def public_legal():
    legal = await db.settings.find_one({"key": "legal_pdf"})
    if not legal:
        return {"available": False, "updated_at": None}
    return {"available": True, "updated_at": legal["updated_at"].isoformat()}


@api_router.get("/public/legal.pdf")
async def public_legal_pdf():
    legal = await db.settings.find_one({"key": "legal_pdf"})
    if not legal:
        raise HTTPException(status_code=404, detail="Todavía no hay acuerdo legal publicado")
    data, _ = await get_object(legal["path"])
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="acuerdo-legal-weed-lemon.pdf"'})


@api_router.post("/settings/legal-pdf")
async def upload_legal_pdf(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    data = await read_limited(file, 10 * 1024 * 1024, "El PDF no puede superar 10 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="El archivo tiene que ser un PDF")
    path = await store_file(data, "application/pdf", file.filename or "acuerdo.pdf", "legal", user["id"])
    await db.settings.update_one(
        {"key": "legal_pdf"},
        {"$set": {"path": path, "filename": file.filename, "updated_at": now_utc(), "updated_by": user["name"]}},
        upsert=True)
    await log_activity(user, "acuerdo_legal", f"Acuerdo legal actualizado ({file.filename})")
    return {"available": True}


@api_router.get("/alta/qr.png")
async def alta_qr(url: str = Query(..., max_length=300)):
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="URL no válida")
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=10, border=2, dark="#0f172a")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@api_router.get("/files/{path:path}")
async def download_file(path: str, user: dict = Depends(get_current_user)):
    record = await db.files.find_one({"storage_path": path, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    data, content_type = await get_object(path)
    media = record.get("content_type") or content_type
    if media not in ("image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"):
        media = "application/octet-stream"  # archivos antiguos de tipo dudoso: se descargan, no se ejecutan
    headers = {"Cache-Control": "private, no-store"}
    if media.startswith("image/"):
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return Response(content=data, media_type=media, headers=headers)


# ---------- categories ----------

DEFAULT_CATEGORIES = [
    {"key": "sativa", "label": "Flor Sativa", "color": "amber"},
    {"key": "indica", "label": "Flor Índica", "color": "purple"},
    {"key": "extracto", "label": "Extracto", "color": "orange"},
    {"key": "comestible", "label": "Comestible", "color": "pink"},
    {"key": "accesorio", "label": "Accesorio", "color": "sky"},
]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return "-".join(text.lower().split())


class CategoryIn(BaseModel):
    label: str
    color: str = "emerald"
    parent: Optional[str] = None  # clave de la categoría madre si es una subcategoría (un solo nivel)


# Orden único de categorías (TPV, catálogo, gestión y recuento), según palabras clave del nombre:
# flores/marihuana → hash/hachís → extractos → dry → polen → el resto en orden alfabético.
# Cada categoría madre va seguida de sus subcategorías, ordenadas con el mismo criterio.
SECTION_PRIORITY = [("flor", "marihuana", "marijuana"), ("hash", "hachis"), ("extracto",), ("dry",), ("polen",)]


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()


def section_sort_key(label: str):
    t = plain(label)
    for rank, words in enumerate(SECTION_PRIORITY):
        if any(w in t for w in words):
            return (rank, t)
    return (len(SECTION_PRIORITY), t)


def ordered_categories(cats: list) -> list:
    keys = {c["key"] for c in cats}
    children = {}
    for c in cats:
        if c.get("parent") in keys:
            children.setdefault(c["parent"], []).append(c)
    tops = [c for c in cats if c.get("parent") not in keys]  # sin madre (o con una madre que ya no existe)
    out = []
    for c in sorted(tops, key=lambda c: section_sort_key(c["label"])):
        out.append(c)
        out.extend(sorted(children.get(c["key"], []), key=lambda k: section_sort_key(k["label"])))
    return out


async def category_and_children(key: str) -> list:
    return [key] + [c["key"] for c in await db.categories.find({"parent": key}).to_list(500)]


async def valid_parent(parent_key: Optional[str], self_key: Optional[str] = None) -> Optional[dict]:
    if not parent_key:
        return None
    if parent_key == self_key:
        raise HTTPException(status_code=400, detail="Una categoría no puede ser subcategoría de sí misma")
    parent = await db.categories.find_one({"key": parent_key})
    if not parent:
        raise HTTPException(status_code=400, detail="La categoría madre no existe")
    if parent.get("parent"):
        raise HTTPException(status_code=400, detail=f"«{parent['label']}» ya es una subcategoría: solo se permite un nivel")
    return parent


@api_router.get("/categories")
async def list_categories(user: dict = Depends(require_staff)):
    docs = await db.categories.find().to_list(500)
    return [ser(d) for d in ordered_categories(docs)]


@api_router.post("/categories")
async def create_category(body: CategoryIn, user: dict = Depends(require_staff)):
    label = body.label.strip()
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="Nombre no válido")
    parent = await valid_parent(body.parent)
    if await db.categories.find_one({"key": key}):
        # Una subcategoría puede llamarse igual que otra categoría ("Índica" dentro de "Flores")
        if parent and not await db.categories.find_one({"key": f"{parent['key']}-{key}"}):
            key = f"{parent['key']}-{key}"
        else:
            raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre"
                                + (f" dentro de «{parent['label']}»" if parent else ""))
    doc = {"key": key, "label": label, "color": body.color, "parent": parent["key"] if parent else None, "created_at": now_utc()}
    result = await db.categories.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "categoria_creada",
                       f"Nueva subcategoría «{label}» dentro de «{parent['label']}»" if parent else f"Nueva categoría «{label}»")
    return ser(doc)


@api_router.patch("/categories/{cat_id}")
async def update_category(cat_id: str, body: CategoryIn, user: dict = Depends(require_staff)):
    target = await db.categories.find_one({"_id": oid(cat_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    if not body.label.strip():
        raise HTTPException(status_code=400, detail="Nombre no válido")
    parent = await valid_parent(body.parent, target["key"])
    if parent and await db.categories.count_documents({"parent": target["key"]}):
        raise HTTPException(status_code=400, detail=f"«{target['label']}» tiene subcategorías: no puede ser subcategoría de otra")
    await db.categories.update_one({"_id": target["_id"]}, {"$set": {"label": body.label.strip(), "color": body.color,
                                                                     "parent": parent["key"] if parent else None}})
    await log_activity(user, "categoria_editada", f"Categoría «{body.label.strip()}» actualizada"
                       + (f" (dentro de «{parent['label']}»)" if parent else ""))
    return ser(await db.categories.find_one({"_id": target["_id"]}))


@api_router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, user: dict = Depends(require_staff)):
    target = await db.categories.find_one({"_id": oid(cat_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    subs = await db.categories.count_documents({"parent": target["key"]})
    if subs > 0:
        raise HTTPException(status_code=400, detail=f"No se puede eliminar: tiene {subs} subcategoría{'s' if subs != 1 else ''}. Elimínalas o muévelas antes")
    used = await db.products.count_documents({"category": target["key"]})
    if used > 0:
        raise HTTPException(status_code=400, detail=f"No se puede eliminar: {used} productos usan esta categoría")
    await db.categories.delete_one({"_id": ObjectId(cat_id)})
    await log_activity(user, "categoria_eliminada", f"Categoría «{target['label']}» eliminada")
    return {"ok": True}


# ---------- products ----------

@api_router.get("/products")
async def list_products(q: Optional[str] = None, category: Optional[str] = None,
                        active_only: bool = False, user: dict = Depends(require_staff)):
    query = {}
    if active_only:
        query["active"] = True
    if category:  # una categoría madre incluye los productos de sus subcategorías
        query["category"] = {"$in": await category_and_children(category)}
    if q:
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    docs = await db.products.find(query).sort("name", 1).to_list(500)
    # "available" = stock menos lo ya vendido fuera de turno (aún sin descontar). El TPV oculta
    # automáticamente los productos con available <= 0.
    reserved = await pending_out_of_shift_qty()
    out = []
    for d in docs:
        item = ser(d)
        item["available"] = round((d.get("stock") or 0) - reserved.get(item["id"], 0), 3)
        out.append(item)
    return out


def validate_product(body: ProductBase):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if body.price < 0:
        raise HTTPException(status_code=400, detail="El precio no puede ser negativo")


async def record_stock_movement(product: dict, type_: str, delta: float, before: float, reason: str,
                                user: dict, session_id: Optional[str] = None):
    await db.stock_movements.insert_one({
        "product_id": str(product["_id"]),
        "product_name": product["name"],
        "unit": product.get("unit", "g"),
        "type": type_,
        "qty": round(delta, 3),
        "stock_before": round(before, 3),
        "stock_after": round(before + delta, 3),
        "reason": reason,
        "session_id": session_id,
        "created_by": user.get("name"),
        "created_by_id": user.get("id"),
        "created_at": now_utc(),
    })


@api_router.post("/products")
async def create_product(body: ProductCreate, user: dict = Depends(require_staff)):
    validate_product(body)
    if body.unit not in ["g", "ud"]:
        raise HTTPException(status_code=400, detail="Unidad no válida")
    if body.initial_stock < 0:
        raise HTTPException(status_code=400, detail="El stock inicial no puede ser negativo")
    if body.unit == "ud" and not is_whole(body.initial_stock):
        raise HTTPException(status_code=400, detail="Un producto por unidades necesita un stock inicial entero")
    doc = body.model_dump(exclude={"initial_stock"})
    doc["name"] = doc["name"].strip()
    doc["stock"] = round(body.initial_stock, 3)
    doc["created_at"] = now_utc()
    result = await db.products.insert_one(doc)
    doc["_id"] = result.inserted_id
    if doc["stock"] > 0:
        await record_stock_movement(doc, "alta", doc["stock"], 0, "Stock inicial del alta", user)
    await log_activity(user, "producto_creado",
                       f"Nuevo producto «{doc['name']}» ({doc['price']} Cr/{doc['unit']}, stock inicial {doc['stock']}{doc['unit']})")
    return ser(doc)


@api_router.patch("/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate, user: dict = Depends(require_staff)):
    validate_product(body)
    target = await db.products.find_one({"_id": oid(product_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    updates = body.model_dump()
    updates["name"] = updates["name"].strip()
    await db.products.update_one({"_id": target["_id"]}, {"$set": updates})
    await log_activity(user, "producto_editado", f"Editado «{updates['name']}» ({updates['price']} Cr/{target.get('unit', 'g')})")
    return ser(await db.products.find_one({"_id": target["_id"]}))


@api_router.post("/products/{product_id}/stock")
async def stock_movement(product_id: str, body: StockMoveIn, user: dict = Depends(require_staff)):
    if body.type not in ["entrada", "merma", "ajuste"]:
        raise HTTPException(status_code=400, detail="Tipo de movimiento no válido")
    reason = (body.reason or "").strip()
    if not reason and body.type != "entrada":
        raise HTTPException(status_code=400, detail="El motivo es obligatorio para mermas y ajustes")
    session = await get_active_session()
    if session and session["status"] in ("opening", "closing"):
        raise HTTPException(status_code=400, detail=f"La caja está {STATUS_TEXT[session['status']]}: los ajustes de stock están bloqueados hasta terminar el recuento")
    product = await db.products.find_one({"_id": oid(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if abs(body.qty) > MAX_QTY:
        raise HTTPException(status_code=400, detail="Cantidad fuera de rango")
    require_whole_units(product, body.qty)
    if body.type in ("entrada", "merma"):
        if body.qty <= 0:
            raise HTTPException(status_code=400, detail="La cantidad tiene que ser mayor que 0")
        delta = body.qty if body.type == "entrada" else -body.qty
    else:
        delta = body.qty
        if abs(delta) < 1e-9:
            raise HTTPException(status_code=400, detail="El stock contado coincide con el del sistema: no hay nada que ajustar")
    delta = round(delta, 3)
    query = {"_id": product["_id"]}
    if delta < 0:
        # Lo vendido fuera de turno ya está comprometido: no se puede dar de baja ese stock,
        # o al abrir el siguiente turno quedaría en negativo.
        reserved = (await pending_out_of_shift_qty()).get(str(product["_id"]), 0)
        query["stock"] = {"$gte": -delta + reserved - 1e-9}
    res = await db.products.update_one(query, {"$inc": {"stock": delta}})
    if res.modified_count == 0:
        raise HTTPException(status_code=400, detail="El stock no puede quedar en negativo (ten en cuenta lo vendido fuera de turno pendiente de descontar)")
    updated = await db.products.find_one({"_id": product["_id"]})
    before = round(updated["stock"] - delta, 3)
    await record_stock_movement(product, body.type, delta, before, reason or None, user,
                                str(session["_id"]) if session else None)
    unit = product.get("unit", "g")
    await log_activity(user, "stock_" + body.type,
                       f"{body.type.capitalize()} de {'+' if delta > 0 else ''}{delta}{unit} en «{product['name']}»{' · ' + reason if reason else ''} "
                       f"(stock {before} → {round(updated['stock'], 3)}{unit})")
    return ser(updated)


@api_router.get("/products/{product_id}/stock-movements")
async def list_stock_movements(product_id: str, user: dict = Depends(require_staff)):
    docs = await db.stock_movements.find({"product_id": product_id}).sort("created_at", -1).to_list(200)
    return [ser(d) for d in docs]


@api_router.patch("/products/{product_id}/toggle")
async def toggle_product(product_id: str, user: dict = Depends(require_staff)):
    target = await db.products.find_one({"_id": ObjectId(product_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    new_state = not target.get("active", True)
    await db.products.update_one({"_id": ObjectId(product_id)}, {"$set": {"active": new_state}})
    await log_activity(user, "producto_estado", f"«{target['name']}» {'activado' if new_state else 'desactivado'}")
    return {"ok": True, "active": new_state}


@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str, user: dict = Depends(require_staff)):
    target = await db.products.find_one({"_id": ObjectId(product_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    await db.products.delete_one({"_id": ObjectId(product_id)})
    await log_activity(user, "producto_eliminado", f"Eliminado «{target['name']}»")
    return {"ok": True}


# ---------- sales ----------

async def pending_out_of_shift_qty() -> dict:
    """Cantidades ya vendidas fuera de turno cuyo stock aún no se ha descontado."""
    reserved = {}
    docs = await db.sales.find({"out_of_shift": True, "out_of_shift_pending": True}).to_list(5000)
    for s in docs:
        for it in s["items"]:
            reserved[it["product_id"]] = reserved.get(it["product_id"], 0) + it["qty"]
    return reserved


async def out_of_shift_pending_summary() -> dict:
    """Ventas (count/total) y recargas (recharges_count/recharges_total) hechas sin turno abierto."""
    docs = await db.sales.find({"out_of_shift": True, "out_of_shift_pending": True}).to_list(5000)
    recs = await db.recharges.find({"out_of_shift": True, "out_of_shift_pending": True}).to_list(5000)
    return {"count": len(docs), "total": round(sum(s["total"] for s in docs), 2),
            "recharges_count": len(recs), "recharges_total": round(sum(r["amount"] for r in recs), 2)}


@api_router.post("/sales")
async def create_sale(body: SaleCreate, user: dict = Depends(require_staff)):
    if not body.items:
        raise HTTPException(status_code=400, detail="El carrito está vacío")
    session = await get_active_session()
    if session and session["status"] != "open":
        raise HTTPException(status_code=400, detail=f"La caja está {STATUS_TEXT[session['status']]}: las ventas están en pausa hasta terminar")
    out_of_shift = session is None
    socio = None
    if body.socio_id:
        socio = await db.users.find_one({"_id": oid(body.socio_id), "member_number": {"$exists": True}})
    if not socio:
        raise HTTPException(status_code=400, detail="Asigna un socio para cobrar desde su saldo")
    if socio.get("status") == "pendiente":
        raise HTTPException(status_code=400, detail=f"El alta de {socio['name']} está pendiente: actívala en Socios antes de dispensar")
    if socio.get("status") == "suspendida":
        raise HTTPException(status_code=400, detail=f"{socio['name']} tiene la cuenta suspendida")

    requested = {}
    for item in body.items:
        if item.qty <= 0:
            raise HTTPException(status_code=400, detail="Cantidad no válida")
        requested[item.product_id] = requested.get(item.product_id, 0) + item.qty
    reserved = await pending_out_of_shift_qty() if out_of_shift else {}
    products = {}
    for pid, qty in requested.items():
        product = await db.products.find_one({"_id": oid(pid)})
        if not product or not product.get("active", True):
            raise HTTPException(status_code=400, detail="Producto no disponible")
        available = round(product.get("stock", 0) - reserved.get(pid, 0), 3)
        if available < qty - 1e-9:
            raise HTTPException(status_code=400, detail=f"Stock insuficiente de «{product['name']}» (quedan {max(available, 0)}{product['unit']})")
        products[pid] = product

    for item in body.items:
        require_whole_units(products[item.product_id], item.qty)

    lines = []
    total = 0.0
    for item in body.items:
        product = products[item.product_id]
        qty = round(item.qty, 3)
        line_total = round(product["price"] * qty, 2)
        total += line_total
        lines.append({
            "product_id": item.product_id,
            "name": product["name"],
            "category": product["category"],
            "unit": product["unit"],
            "price": product["price"],
            "qty": qty,
            "line_total": line_total,
        })
    total = round(total, 2)
    # En turno el stock se descuenta ya; fuera de turno se descuenta al abrir la siguiente caja.
    # El descuento es condicional y atómico: si otra venta simultánea se ha llevado el stock,
    # se deshace lo descontado y la venta se rechaza (nunca queda stock negativo).
    if not out_of_shift:
        done = []
        for pid, qty in requested.items():
            q = round(qty, 3)
            res = await db.products.update_one({"_id": oid(pid), "stock": {"$gte": q - 1e-9}}, {"$inc": {"stock": -q}})
            if res.modified_count == 0:
                for done_pid, done_q in done:
                    await db.products.update_one({"_id": oid(done_pid)}, {"$inc": {"stock": done_q}})
                raise HTTPException(status_code=409, detail=f"Stock insuficiente de «{products[pid]['name']}»: alguien acaba de venderlo. Revisa el ticket.")
            done.append((pid, q))
    await db.users.update_one({"_id": socio["_id"]}, {"$inc": {"balance": -total}})
    ticket = await next_seq("ticket")
    sale = {
        "ticket_number": f"T-{ticket:05d}",
        "items": lines,
        "total": total,
        "payment_method": "saldo",
        "socio_id": str(socio["_id"]),
        "socio_name": socio["name"],
        "socio_member_number": socio.get("member_number"),
        "cajero_id": user["id"],
        "cajero_name": user["name"],
        "cash_session_id": None if out_of_shift else str(session["_id"]),
        "out_of_shift": out_of_shift,
        "out_of_shift_pending": out_of_shift,
        "created_at": now_utc(),
    }
    result = await db.sales.insert_one(sale)
    sale["_id"] = result.inserted_id
    new_balance = round((socio.get("balance") or 0) - total, 2)
    nota = f" · saldo resultante {new_balance} Cr" + (" (DEUDA)" if new_balance < 0 else "")
    if out_of_shift:
        nota += " · FUERA DE TURNO"
    await log_activity(user, "venta", f"Ticket {sale['ticket_number']} · {total} Cr del saldo de {socio['name']}{nota}")
    return ser(sale)


@api_router.get("/sales")
async def list_sales(range: str = "today", payment: Optional[str] = None,
                     socio_id: Optional[str] = None, user: dict = Depends(require_staff)):
    if user["role"] != "admin" and not socio_id:
        raise HTTPException(status_code=403, detail="El histórico completo de ventas es solo para administración")
    query = {}
    start, _ = day_bounds_madrid(now_utc())
    if range == "today":
        query["created_at"] = {"$gte": start}
    elif range == "7d":
        query["created_at"] = {"$gte": start - timedelta(days=6)}
    elif range == "30d":
        query["created_at"] = {"$gte": start - timedelta(days=29)}
    if payment:
        query["payment_method"] = payment
    if socio_id:
        query["socio_id"] = socio_id
    docs = await db.sales.find(query).sort("created_at", -1).to_list(500)
    return [ser(d) for d in docs]


@api_router.get("/sales/{sale_id}")
async def get_sale(sale_id: str, user: dict = Depends(require_staff)):
    doc = await db.sales.find_one({"_id": ObjectId(sale_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    return ser(doc)


# ---------- cash register ----------
#
# Ciclo de un turno (uno solo activo por local):
#   POST /cash/open               → "opening": incorpora las ventas fuera de turno (descuenta su stock)
#                                   y crea el recuento de apertura.
#   POST /cash/opening/confirm    → "open": exige todo el stock contado.
#   POST /cash/closing/start      → "closing": ventas, recargas y ajustes de stock en pausa.
#   POST /cash/closing/cash       → arqueo de efectivo.
#   POST /cash/closing/stocktake/start → recuento de cierre.
#   POST /cash/closing/finalize   → "closed".
# Al confirmar la apertura y al cerrar, lo contado pasa a ser el stock del sistema (si se marca
# "contado = esperado" el stock queda igual). Las diferencias quedan registradas en el informe.

STOCKTAKE_SCOPE = "productos activos y cualquier producto con existencias, agrupados por categoría"

# Las secciones del recuento son las categorías madre, en el mismo orden que el TPV (ordered_categories).
# Los productos de una subcategoría se cuentan dentro de la sección de su madre.


def can_operate(session: dict, user: dict) -> bool:
    return user["role"] == "admin" or session.get("opened_by_id") == user["id"]


def state_error(session: Optional[dict], expected: str) -> HTTPException:
    if not session:
        return HTTPException(status_code=400, detail="No hay ningún turno de caja activo")
    if session["status"] == "opening":
        return HTTPException(status_code=400, detail="La caja está en apertura: termina primero el recuento de stock")
    if session["status"] == "closing":
        return HTTPException(status_code=400, detail="La caja está en proceso de cierre")
    if expected == "closing":
        return HTTPException(status_code=400, detail="Inicia primero el cierre del turno")
    return HTTPException(status_code=400, detail="El turno ya está abierto")


async def require_session(user: dict, *statuses: str) -> dict:
    session = await get_active_session()
    if not session or session["status"] not in statuses:
        raise state_error(session, statuses[0])
    if not can_operate(session, user):
        raise HTTPException(status_code=403, detail=f"Este turno es de {session['opened_by']}: solo esa persona o un administrador pueden operarlo")
    return session


def stocktake_kind(session: dict) -> str:
    return "opening" if session["status"] == "opening" else "closing"


async def get_draft_stocktake(session: dict, kind: Optional[str] = None):
    return await db.stocktakes.find_one({"session_id": str(session["_id"]),
                                         "kind": kind or stocktake_kind(session), "status": "draft"})


async def build_stocktake(session: dict, kind: str, user: dict) -> dict:
    cats = ordered_categories(await db.categories.find().to_list(500))
    by_key = {c["key"]: c for c in cats}
    pos = {c["key"]: i for i, c in enumerate(cats)}
    products = await db.products.find({"$or": [{"active": True}, {"stock": {"$gt": 0}}]}).sort("name", 1).to_list(5000)
    lines, order = [], {}
    for p in products:
        cat = by_key.get(p.get("category"))
        top = by_key.get(cat.get("parent")) if cat and cat.get("parent") in by_key else cat
        label = top["label"] if top else (p.get("category") or "Sin categoría")
        line = {
            "product_id": str(p["_id"]),
            "name": p["name"],
            "unit": p.get("unit", "g"),
            "category": p.get("category"),
            "category_label": label,  # sección = categoría madre
            "subcategory_label": cat["label"] if cat and top is not cat else None,
            "expected": round(p.get("stock", 0) or 0, 3),
            "price": p.get("price"),  # para decidir qué descuadres salen en el PDF
            "counted": None,
            "difference": None,
        }
        # categorías conocidas en el orden del TPV; las desconocidas al final, con el mismo criterio de palabras
        order[line["product_id"]] = (pos[top["key"]] if top else len(cats), section_sort_key(label),
                                     pos[cat["key"]] if cat else 0, plain(p["name"]))
        lines.append(line)
    lines.sort(key=lambda l: order[l["product_id"]])
    doc = {
        "session_id": str(session["_id"]),
        "kind": kind,
        "status": "draft",
        "scope": STOCKTAKE_SCOPE,
        "sections": list(dict.fromkeys(l["category_label"] for l in lines)),
        "lines": lines,
        "version": 1,
        "created_by": user["name"],
        "created_at": now_utc(),
    }
    result = await db.stocktakes.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def stocktake_summary(st: dict) -> dict:
    pend = [l for l in st["lines"] if l["counted"] is None]
    diffs = [l for l in st["lines"] if l["difference"] is not None and abs(l["difference"]) > 1e-9]
    return {"pendientes": len(pend), "diferencias": len(diffs), "total": len(st["lines"])}


async def save_stocktake_lines(st: dict, lines: list, version: int) -> dict:
    res = await db.stocktakes.update_one({"_id": st["_id"], "version": version, "status": "draft"},
                                         {"$set": {"lines": lines, "updated_at": now_utc()}, "$inc": {"version": 1}})
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="El recuento ha cambiado en otro dispositivo; se ha recargado")
    return ser(await db.stocktakes.find_one({"_id": st["_id"]}))


async def apply_stocktake_to_stock(st: dict, session: dict, user: dict) -> int:
    """Lo contado pasa a ser el stock del sistema. Devuelve cuántos productos han cambiado."""
    label = "apertura" if st["kind"] == "opening" else "cierre"
    changed = 0
    for l in st["lines"]:
        if l["counted"] is None or l["difference"] is None or abs(l["difference"]) <= 1e-9:
            continue
        product = await db.products.find_one({"_id": oid(l["product_id"])})
        if not product:
            continue
        before = round(product.get("stock", 0) or 0, 3)
        await db.products.update_one({"_id": product["_id"]}, {"$set": {"stock": l["counted"]}})
        await record_stock_movement(product, "recuento", round(l["counted"] - before, 3), before,
                                    f"Recuento de {label} · turno de {session['opened_by']}", user, str(session["_id"]))
        changed += 1
    return changed


def set_counted(line: dict, counted: Optional[float]):
    if counted is None:
        line["counted"] = None
        line["difference"] = None
    else:
        line["counted"] = round(counted, 3)
        line["difference"] = round(line["counted"] - line["expected"], 3)


async def session_totals(session):
    sid = str(session["_id"])
    sales = await db.sales.find({"cash_session_id": sid}).to_list(10000)
    ventas_saldo = round(sum(s["total"] for s in sales if s.get("payment_method") == "saldo"), 2)
    # Compatibilidad con turnos antiguos en los que se cobraba en efectivo directamente.
    ventas_efectivo = round(sum(s["total"] for s in sales if s.get("payment_method") == "efectivo"), 2)
    recharges = await db.recharges.find({"session_id": sid}).to_list(10000)
    rec_efectivo = round(sum(r["amount"] for r in recharges if r.get("method", "efectivo") == "efectivo"), 2)
    rec_tarjeta = round(sum(r["amount"] for r in recharges if r.get("method") == "tarjeta"), 2)
    neg = await db.users.find({"balance": {"$lt": 0}}).to_list(5000)
    deuda = round(sum(-(u.get("balance") or 0) for u in neg), 2)
    movements = await db.cash_movements.find({"session_id": sid}).sort("created_at", -1).to_list(500)
    entradas = round(sum(m["amount"] for m in movements if m["type"] == "in"), 2)
    salidas = round(sum(m["amount"] for m in movements if m["type"] == "out"), 2)
    esperado = round(session.get("starting_amount", 0) + rec_efectivo + ventas_efectivo + entradas - salidas, 2)
    return {
        "ventas_count": len(sales),
        "ventas_saldo": ventas_saldo,
        "ventas_efectivo": ventas_efectivo,
        "recargas": round(rec_efectivo + rec_tarjeta, 2),
        "recargas_efectivo": rec_efectivo,
        "recargas_tarjeta": rec_tarjeta,
        "deuda_socios": deuda,
        "entradas": entradas,
        "salidas": salidas,
        "esperado": esperado,
        "movements": [ser(m) for m in movements],
    }


@api_router.get("/cash/current")
async def cash_current(user: dict = Depends(require_staff)):
    pending = await out_of_shift_pending_summary()
    session = await get_active_session()
    if not session:
        return {"session": None, "totals": None, "stocktake": None, "out_of_shift_pending": pending}
    totals = await session_totals(session)
    stocktake = None
    if session["status"] in ("opening", "closing"):
        stocktake = ser(await get_draft_stocktake(session))
    return {"session": ser(session), "totals": totals, "stocktake": stocktake, "out_of_shift_pending": pending}


@api_router.post("/cash/open")
async def cash_open(body: CashOpenIn, user: dict = Depends(require_staff)):
    if await get_active_session():
        raise HTTPException(status_code=400, detail="Ya hay un turno de caja activo")
    if body.starting_amount < 0:
        raise HTTPException(status_code=400, detail="El fondo inicial no puede ser negativo")
    doc = {
        "opened_by": user["name"],
        "opened_by_id": user["id"],
        "opened_at": now_utc(),
        "opening_started_at": now_utc(),
        "starting_amount": round(body.starting_amount, 2),
        "status": "opening",
        "active_lock": "local",  # índice único: impide dos turnos activos a la vez
    }
    try:
        result = await db.cash_sessions.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Ya hay un turno de caja activo")
    doc["_id"] = result.inserted_id
    sid = str(doc["_id"])

    # Ventas fuera de turno: pasan obligatoriamente a este turno y su stock se descuenta antes del recuento.
    pending = await db.sales.find({"out_of_shift": True, "out_of_shift_pending": True}).sort("created_at", 1).to_list(5000)
    for s in pending:
        for it in s["items"]:
            await db.products.update_one({"_id": oid(it["product_id"])}, {"$inc": {"stock": -it["qty"]}})
        await db.sales.update_one({"_id": s["_id"]}, {"$set": {
            "out_of_shift_pending": False, "cash_session_id": sid, "absorbed_at": now_utc()}})
    # Recargas fuera de turno: su efectivo pasa al esperado de este turno.
    pending_rec = await db.recharges.find({"out_of_shift": True, "out_of_shift_pending": True}).sort("created_at", 1).to_list(5000)
    for r in pending_rec:
        await db.recharges.update_one({"_id": r["_id"]}, {"$set": {
            "out_of_shift_pending": False, "session_id": sid, "absorbed_at": now_utc()}})
    absorbed = {
        "out_of_shift_count": len(pending),
        "out_of_shift_total": round(sum(s["total"] for s in pending), 2),
        "out_of_shift_sale_ids": [str(s["_id"]) for s in pending],
        "out_of_shift_recharge_count": len(pending_rec),
        "out_of_shift_recharge_total": round(sum(r["amount"] for r in pending_rec), 2),
        "out_of_shift_recharge_ids": [str(r["_id"]) for r in pending_rec],
    }
    await db.cash_sessions.update_one({"_id": doc["_id"]}, {"$set": absorbed})
    doc.update(absorbed)
    await build_stocktake(doc, "opening", user)
    extra = f" · {absorbed['out_of_shift_count']} ventas fuera de turno incorporadas ({absorbed['out_of_shift_total']} Cr)" if pending else ""
    if pending_rec:
        extra += f" · {len(pending_rec)} recargas fuera de turno incorporadas ({absorbed['out_of_shift_recharge_total']} Cr en efectivo)"
    await log_activity(user, "caja_apertura_iniciada", f"Apertura de turno iniciada con {doc['starting_amount']} Cr de fondo{extra}")
    return ser(doc)


@api_router.post("/cash/opening/confirm")
async def cash_opening_confirm(user: dict = Depends(require_staff)):
    session = await require_session(user, "opening")
    st = await get_draft_stocktake(session, "opening")
    if not st:
        raise HTTPException(status_code=400, detail="No hay recuento de apertura")
    summary = stocktake_summary(st)
    if summary["pendientes"]:
        raise HTTPException(status_code=400, detail=f"Quedan {summary['pendientes']} productos pendientes de contar")
    changed = await apply_stocktake_to_stock(st, session, user)
    await db.stocktakes.update_one({"_id": st["_id"]}, {"$set": {
        "status": "final", "finalized_at": now_utc(), "finalized_by": user["name"], "stock_updated": changed}})
    await db.cash_sessions.update_one({"_id": session["_id"]}, {"$set": {
        "status": "open", "opened_at": now_utc(), "opening_confirmed_by": user["name"]}})
    await log_activity(user, "caja_abierta",
                       f"Turno de {session['opened_by']} abierto con {session['starting_amount']} Cr de fondo · "
                       f"recuento de apertura: {changed} productos con el stock actualizado a lo contado")
    return ser(await db.cash_sessions.find_one({"_id": session["_id"]}))


@api_router.post("/cash/opening/cancel")
async def cash_opening_cancel(user: dict = Depends(require_admin)):
    session = await get_active_session()
    if not session or session["status"] != "opening":
        raise HTTPException(status_code=400, detail="No hay ninguna apertura en curso")
    # Las ventas fuera de turno vuelven a quedar pendientes y se restaura su stock.
    ids = [oid(i) for i in session.get("out_of_shift_sale_ids", [])]
    sales = await db.sales.find({"_id": {"$in": ids}}).to_list(5000) if ids else []
    for s in sales:
        for it in s["items"]:
            await db.products.update_one({"_id": oid(it["product_id"])}, {"$inc": {"stock": it["qty"]}})
        await db.sales.update_one({"_id": s["_id"]}, {"$set": {"out_of_shift_pending": True, "cash_session_id": None},
                                                      "$unset": {"absorbed_at": ""}})
    rec_ids = [oid(i) for i in session.get("out_of_shift_recharge_ids", [])]
    if rec_ids:
        await db.recharges.update_many({"_id": {"$in": rec_ids}}, {"$set": {"out_of_shift_pending": True, "session_id": None},
                                                                  "$unset": {"absorbed_at": ""}})
    await db.stocktakes.update_many({"session_id": str(session["_id"]), "status": "draft"},
                                    {"$set": {"status": "cancelled", "cancelled_at": now_utc(), "cancelled_by": user["name"]}})
    await db.cash_sessions.update_one({"_id": session["_id"]}, {
        "$set": {"status": "cancelled", "cancelled_at": now_utc(), "cancelled_by": user["name"]},
        "$unset": {"active_lock": ""}})
    await log_activity(user, "caja_apertura_cancelada",
                       f"Apertura del turno de {session['opened_by']} cancelada por administración · "
                       f"{len(sales)} ventas y {len(rec_ids)} recargas fuera de turno vuelven a pendientes")
    return {"ok": True}


@api_router.post("/cash/movements")
async def cash_movement(body: CashMovementIn, user: dict = Depends(require_staff)):
    session = await require_session(user, "open")
    if body.type not in ["in", "out"] or body.amount <= 0:
        raise HTTPException(status_code=400, detail="Movimiento no válido")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="El motivo es obligatorio")
    amount = round(body.amount, 2)
    if body.type == "out":
        totals = await session_totals(session)
        if amount > totals["esperado"] + 1e-9:
            raise HTTPException(status_code=400, detail=f"No hay tanto efectivo en caja (disponible {totals['esperado']} Cr)")
    doc = {
        "session_id": str(session["_id"]),
        "type": body.type,
        "amount": amount,
        "reason": reason,
        "created_by": user["name"],
        "created_at": now_utc(),
    }
    result = await db.cash_movements.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "movimiento_caja", f"{'Entrada' if body.type == 'in' else 'Salida'} de {amount} Cr · {reason}")
    return ser(doc)


@api_router.post("/cash/closing/start")
async def cash_closing_start(user: dict = Depends(require_staff)):
    session = await require_session(user, "open")
    await db.cash_sessions.update_one({"_id": session["_id"]}, {"$set": {
        "status": "closing", "closing_started_at": now_utc(), "closing_started_by": user["name"]}})
    await log_activity(user, "caja_cierre_iniciado", f"Cierre del turno de {session['opened_by']} iniciado")
    return ser(await db.cash_sessions.find_one({"_id": session["_id"]}))


@api_router.post("/cash/closing/cash")
async def cash_closing_cash(body: ClosingCashIn, user: dict = Depends(require_staff)):
    session = await require_session(user, "closing")
    if body.counted is None or body.counted < 0:
        raise HTTPException(status_code=400, detail="Escribe el efectivo contado (0 si no hay nada)")
    totals = await session_totals(session)
    counted = round(body.counted, 2)
    cash_count = {
        "expected": totals["esperado"],
        "counted": counted,
        "difference": round(counted - totals["esperado"], 2),
        "reason": (body.reason or "").strip() or None,
        "by": user["name"],
        "at": now_utc(),
    }
    await db.cash_sessions.update_one({"_id": session["_id"]}, {"$set": {"cash_count": cash_count}})
    await log_activity(user, "caja_arqueo",
                       f"Arqueo: esperado {cash_count['expected']} Cr, contado {counted} Cr (diferencia {cash_count['difference']})")
    return ser(await db.cash_sessions.find_one({"_id": session["_id"]}))


@api_router.post("/cash/closing/stocktake/start")
async def cash_closing_stocktake_start(user: dict = Depends(require_staff)):
    session = await require_session(user, "closing")
    if not session.get("cash_count"):
        raise HTTPException(status_code=400, detail="Guarda primero el arqueo de efectivo")
    st = await get_draft_stocktake(session, "closing")
    if not st:
        st = await build_stocktake(session, "closing", user)
    return ser(st)


@api_router.patch("/cash/stocktake/line")
async def cash_stocktake_line(body: StocktakeLineIn, user: dict = Depends(require_staff)):
    session = await require_session(user, "opening", "closing")
    st = await get_draft_stocktake(session)
    if not st:
        raise HTTPException(status_code=400, detail="No hay ningún recuento en curso")
    if body.counted is not None and body.counted < 0:
        raise HTTPException(status_code=400, detail="La cantidad contada no puede ser negativa")
    if body.counted is not None and body.counted > MAX_QTY:
        raise HTTPException(status_code=400, detail="Cantidad contada fuera de rango")
    lines = st["lines"]
    line = next((l for l in lines if l["product_id"] == body.product_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Ese producto no está en el recuento")
    if body.counted is not None and line.get("unit") == "ud" and not is_whole(body.counted):
        raise HTTPException(status_code=400, detail=f"«{line['name']}» va por unidades: cuenta un número entero")
    set_counted(line, body.counted)
    return await save_stocktake_lines(st, lines, body.version)


@api_router.post("/cash/stocktake/autofill")
async def cash_stocktake_autofill(body: AutofillIn, user: dict = Depends(require_staff)):
    session = await require_session(user, "opening", "closing")
    st = await get_draft_stocktake(session)
    if not st:
        raise HTTPException(status_code=400, detail="No hay ningún recuento en curso")
    if not body.all and not body.section and not body.product_id:
        raise HTTPException(status_code=400, detail="Indica una sección, un producto o todo el recuento")
    lines = st["lines"]
    touched = 0
    for l in lines:
        if body.all or (body.section and l["category_label"] == body.section) or (body.product_id and l["product_id"] == body.product_id):
            if body.only_pending and l["counted"] is not None:
                continue
            set_counted(l, l["expected"])
            touched += 1
    if not touched:
        if body.only_pending:
            raise HTTPException(status_code=400, detail="No queda nada pendiente de contar")
        raise HTTPException(status_code=404, detail="Nada que rellenar con esa selección")
    return await save_stocktake_lines(st, lines, body.version)


@api_router.post("/cash/closing/finalize")
async def cash_closing_finalize(user: dict = Depends(require_staff)):
    session = await require_session(user, "closing")
    cc = session.get("cash_count")
    if not cc:
        raise HTTPException(status_code=400, detail="Falta el arqueo de efectivo")
    st = await get_draft_stocktake(session, "closing")
    if not st:
        raise HTTPException(status_code=400, detail="Falta el recuento de stock de cierre")
    summary = stocktake_summary(st)
    if summary["pendientes"]:
        raise HTTPException(status_code=400, detail=f"No se puede cerrar: quedan {summary['pendientes']} productos pendientes de contar")
    totals = await session_totals(session)
    changed = await apply_stocktake_to_stock(st, session, user)
    await db.stocktakes.update_one({"_id": st["_id"]}, {"$set": {
        "status": "final", "finalized_at": now_utc(), "finalized_by": user["name"], "stock_updated": changed}})
    await db.cash_sessions.update_one({"_id": session["_id"]}, {
        "$set": {
            "status": "closed",
            "closed_by": user["name"],
            "closed_by_id": user["id"],
            "closed_at": now_utc(),
            "supervised": user["id"] != session.get("opened_by_id"),
            "counted_amount": cc["counted"],
            "expected_amount": cc["expected"],
            "difference": cc["difference"],
            "notes": cc.get("reason"),
            "totals": {k: v for k, v in totals.items() if k != "movements"},
            "stock_differences": summary["diferencias"],
        },
        "$unset": {"active_lock": ""}})
    await log_activity(user, "caja_cerrada",
                       f"Turno de {session['opened_by']} cerrado · esperado {cc['expected']}, contado {cc['counted']} "
                       f"(diferencia {cc['difference']}) · {changed} productos con el stock actualizado a lo contado")
    return ser(await db.cash_sessions.find_one({"_id": session["_id"]}))


@api_router.post("/cash/closing/cancel")
async def cash_closing_cancel(user: dict = Depends(require_admin)):
    session = await get_active_session()
    if not session or session["status"] != "closing":
        raise HTTPException(status_code=400, detail="No hay ningún cierre en curso")
    await db.stocktakes.update_many({"session_id": str(session["_id"]), "kind": "closing", "status": "draft"},
                                    {"$set": {"status": "cancelled", "cancelled_at": now_utc(), "cancelled_by": user["name"]}})
    await db.cash_sessions.update_one({"_id": session["_id"]}, {
        "$set": {"status": "open"},
        "$unset": {"cash_count": "", "closing_started_at": "", "closing_started_by": ""}})
    await log_activity(user, "caja_cierre_cancelado", f"Cierre del turno de {session['opened_by']} cancelado por administración")
    return {"ok": True}


@api_router.get("/cash/sessions")
async def cash_sessions(user: dict = Depends(require_admin)):
    docs = await db.cash_sessions.find({"status": "closed"}).sort("opened_at", -1).to_list(200)
    return [ser(d) for d in docs]


@api_router.get("/cash/sessions/{session_id}")
async def cash_session_report(session_id: str, user: dict = Depends(require_admin)):
    session = await db.cash_sessions.find_one({"_id": oid(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    sid = str(session["_id"])
    closing = await db.stocktakes.find_one({"session_id": sid, "kind": "closing", "status": "final"})
    opening = await db.stocktakes.find_one({"session_id": sid, "kind": "opening", "status": "final"})
    ids = [oid(i) for i in session.get("out_of_shift_sale_ids", [])]
    oos = await db.sales.find({"_id": {"$in": ids}}).sort("created_at", 1).to_list(5000) if ids else []
    rec_ids = [oid(i) for i in session.get("out_of_shift_recharge_ids", [])]
    oos_rec = await db.recharges.find({"_id": {"$in": rec_ids}}).sort("created_at", 1).to_list(5000) if rec_ids else []
    return {
        "out_of_shift_recharges": [{"id": str(r["_id"]), "socio_name": r.get("socio_name"), "amount": r["amount"],
                                    "created_at": r["created_at"]} for r in oos_rec],
        "session": ser(session),
        "stocktake": ser(closing),
        "opening_stocktake": ser(opening),
        "out_of_shift_sales": [{"id": str(s["_id"]), "ticket_number": s["ticket_number"],
                                "socio_name": s.get("socio_name"), "total": s["total"]} for s in oos],
    }


@api_router.get("/cash/sessions/{session_id}/report.pdf")
async def cash_session_pdf(session_id: str, user: dict = Depends(require_staff)):
    """Resumen del cierre en PDF. Lo puede descargar un administrador o el responsable del turno."""
    session = await db.cash_sessions.find_one({"_id": oid(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    if session.get("status") != "closed":
        raise HTTPException(status_code=400, detail="El turno todavía no está cerrado")
    if user["role"] != "admin" and session.get("opened_by_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Solo un administrador o el responsable del turno pueden descargarlo")
    sid = str(session["_id"])
    sales = await db.sales.find({"cash_session_id": sid}).sort("created_at", 1).to_list(20000)
    recharges = await db.recharges.find({"session_id": sid}).to_list(20000)
    movements = await db.cash_movements.find({"session_id": sid}).to_list(2000)
    opening = await db.stocktakes.find_one({"session_id": sid, "kind": "opening", "status": "final"})
    closing = await db.stocktakes.find_one({"session_id": sid, "kind": "closing", "status": "final"})
    prices = {str(p["_id"]): p.get("price") for p in await db.products.find().to_list(10000)}
    pdf = build_closing_pdf(session, sales, recharges, movements, opening, closing, prices=prices)
    closed = as_local(session.get("closed_at"))
    filename = f"cierre-turno-{closed.strftime('%Y-%m-%d-%H%M') if closed else sid}.pdf"
    await log_activity(user, "caja_pdf", f"Descarga del resumen de cierre del turno de {session.get('opened_by')}")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------- dashboard ----------

@api_router.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(require_admin)):
    start_today, _ = day_bounds_madrid(now_utc())
    start_7d = start_today - timedelta(days=6)
    sales_7d = await db.sales.find({"created_at": {"$gte": start_7d}}).to_list(5000)
    for s in sales_7d:
        if isinstance(s["created_at"], datetime) and s["created_at"].tzinfo is None:
            s["created_at"] = s["created_at"].replace(tzinfo=timezone.utc)
    today_sales = [s for s in sales_7d if s["created_at"] >= start_today]

    grams_today = sum(i["qty"] for s in today_sales for i in s["items"] if i["unit"] == "g")

    daily = []
    for i in range(7):
        d_start = start_7d + timedelta(days=i)
        d_end = d_start + timedelta(days=1)
        day_sales = [s for s in sales_7d if d_start <= s["created_at"] < d_end]
        local_day = d_start.astimezone(MADRID)
        daily.append({
            "dia": local_day.strftime("%a").replace(".", ""),
            "total": round(sum(s["total"] for s in day_sales), 2),
            "ventas": len(day_sales),
        })

    top = {}
    for s in sales_7d:
        for i in s["items"]:
            t = top.setdefault(i["name"], {"name": i["name"], "qty": 0, "total": 0.0, "unit": i["unit"]})
            t["qty"] += i["qty"]
            t["total"] += i["line_total"]
    top_products = sorted(top.values(), key=lambda x: -x["total"])[:5]

    low_stock = await db.products.find({"active": True, "stock": {"$lt": 10}}).sort("stock", 1).to_list(10)
    socios_count = await db.users.count_documents({"role": "socio"})
    new_socios = await db.users.count_documents({"role": "socio", "created_at": {"$gte": start_today - timedelta(days=29)}})

    return {
        "today_total": round(sum(s["total"] for s in today_sales), 2),
        "today_count": len(today_sales),
        "grams_today": round(grams_today, 1),
        "socios_count": socios_count,
        "new_socios_30d": new_socios,
        "daily": daily,
        "top_products": top_products,
        "low_stock": [ser(p) for p in low_stock],
    }


# ---------- activity ----------

@api_router.get("/activity")
async def activity(limit: int = 100, user: dict = Depends(require_admin)):
    docs = await db.activity.find().sort("created_at", -1).to_list(min(limit, 500))
    return [ser(d) for d in docs]


@api_router.get("/")
async def root():
    return {"message": "Weed Lemon Social Club POS API", "version": APP_VERSION}


# ---------- seed ----------

PRODUCT_IMAGES = {
    "Lemon Haze": "https://images.pexels.com/photos/30682036/pexels-photo-30682036.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Amnesia Lemon": "https://images.pexels.com/photos/18856172/pexels-photo-18856172.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Purple Punch": "https://images.pexels.com/photos/18856163/pexels-photo-18856163.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Northern Lights": "https://images.pexels.com/photos/35383930/pexels-photo-35383930.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Hachís Frozen": "https://images.pexels.com/photos/5021597/pexels-photo-5021597.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Rosin Limón": "https://images.pexels.com/photos/9259998/pexels-photo-9259998.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Gominolas CBD": "https://images.pexels.com/photos/14945865/pexels-photo-14945865.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Brownie de la casa": "https://images.pexels.com/photos/17488699/pexels-photo-17488699.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Papel + Filtros": "https://images.pexels.com/photos/6039202/pexels-photo-6039202.jpeg?auto=compress&cs=tinysrgb&w=800",
    "Grinder aluminio": "https://images.pexels.com/photos/29474290/pexels-photo-29474290.jpeg?auto=compress&cs=tinysrgb&w=800",
}

SEED_PRODUCTS = [
    {"name": "Lemon Haze", "category": "sativa", "price": 8.5, "unit": "g", "stock": 120, "thc": 21.0, "cbd": 0.3, "description": "Cítrica y energética, la favorita de la casa", "active": True},
    {"name": "Amnesia Lemon", "category": "sativa", "price": 9.0, "unit": "g", "stock": 85, "thc": 23.0, "cbd": 0.2, "description": "Potente con notas de limón", "active": True},
    {"name": "Purple Punch", "category": "indica", "price": 9.5, "unit": "g", "stock": 60, "thc": 20.0, "cbd": 0.5, "description": "Relajante, dulce y afrutada", "active": True},
    {"name": "Northern Lights", "category": "indica", "price": 8.0, "unit": "g", "stock": 95, "thc": 18.0, "cbd": 0.4, "description": "Clásica índica para desconectar", "active": True},
    {"name": "Hachís Frozen", "category": "extracto", "price": 12.0, "unit": "g", "stock": 40, "thc": 35.0, "cbd": 1.0, "description": "Extracción en frío de alta calidad", "active": True},
    {"name": "Rosin Limón", "category": "extracto", "price": 25.0, "unit": "g", "stock": 15, "thc": 68.0, "cbd": 0.5, "description": "Rosin prensado artesanal", "active": True},
    {"name": "Gominolas CBD", "category": "comestible", "price": 6.0, "unit": "ud", "stock": 50, "thc": 0.0, "cbd": 10.0, "description": "Bolsa de gominolas con CBD", "active": True},
    {"name": "Brownie de la casa", "category": "comestible", "price": 7.5, "unit": "ud", "stock": 24, "thc": 5.0, "cbd": 2.0, "description": "Horneado cada mañana", "active": True},
    {"name": "Papel + Filtros", "category": "accesorio", "price": 1.5, "unit": "ud", "stock": 200, "thc": None, "cbd": None, "description": "Pack de librillo y filtros", "active": True},
    {"name": "Grinder aluminio", "category": "accesorio", "price": 12.0, "unit": "ud", "stock": 8, "thc": None, "cbd": None, "description": "Grinder de 4 piezas con logo del club", "active": True},
]

SEED_SOCIOS = [
    {"name": "Lucía", "apellidos": "Fernández", "doc_type": "DNI", "doc_number": "45678901L", "phone": "612345678", "email": "lucia.fernandez@example.com"},
    {"name": "Marco", "apellidos": "Ibáñez", "doc_type": "DNI", "doc_number": "23456789M", "phone": "623456789", "email": "marco.ibanez@example.com"},
    {"name": "Sara", "apellidos": "Delgado", "doc_type": "DNI", "doc_number": "34567890S", "phone": "634567890", "email": None},
]


async def seed_food_and_drinks():
    """Añade una sola vez las categorías Refrescos y Dulces con sus productos (también a bases ya existentes).
    Si luego se borran, no vuelven a aparecer."""
    if await db.settings.find_one({"key": "catalog_food_drinks_v1"}):
        return
    for c in FOOD_DRINK_CATEGORIES:
        if not await db.categories.find_one({"key": c["key"]}):
            await db.categories.insert_one({**c, "created_at": now_utc()})
    added = 0
    for p in FOOD_DRINK_PRODUCTS:
        if not await db.products.find_one({"name": p["name"]}):
            await db.products.insert_one({**p, "created_at": now_utc()})
            added += 1
    await db.settings.update_one({"key": "catalog_food_drinks_v1"}, {"$set": {"at": now_utc(), "products": added}}, upsert=True)
    logger.info("Catálogo de refrescos y dulces añadido (%s productos)", added)


async def migrate():
    """Migraciones idempotentes para bases de datos de versiones anteriores."""
    # Todo usuario (también el equipo) tiene nº de socio y saldo.
    without_number = await db.users.find({"member_number": {"$exists": False}}).sort("created_at", 1).to_list(5000)
    for u in without_number:
        n = await next_seq("member")
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"member_number": f"WL-{n:04d}"}})
    await db.users.update_many({"balance": {"$exists": False}}, {"$set": {"balance": 0.0}})
    # El antiguo campo "dni" pasa a tipo + nº de documento.
    legacy = await db.users.find({"dni": {"$nin": [None, ""]}, "doc_number": {"$exists": False}}).to_list(5000)
    for u in legacy:
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"doc_type": "DNI", "doc_number": norm_doc(u["dni"])}})
    # Turnos abiertos de la versión anterior: se marcan como el turno activo del local.
    await db.cash_sessions.update_many({"status": {"$in": ACTIVE_STATUSES}, "active_lock": {"$exists": False}},
                                       {"$set": {"active_lock": "local"}})


async def startup():
    await db.users.create_index("email")
    await db.users.create_index("doc_number")
    await db.products.create_index("name")
    await db.sales.create_index("created_at")
    await db.sales.create_index([("out_of_shift_pending", 1), ("out_of_shift", 1)])
    await db.sales.create_index("cash_session_id")
    await db.activity.create_index("created_at")
    await db.login_attempts.create_index("identifier")
    await db.stocktakes.create_index([("session_id", 1), ("kind", 1), ("status", 1)])
    await db.stock_movements.create_index([("product_id", 1), ("created_at", -1)])
    await db.public_hits.create_index("at", expireAfterSeconds=60 * 60 * 24)

    if len(os.environ.get("JWT_SECRET", "")) < 32:
        if COOKIE_SECURE:  # producción: con una clave corta se podrían falsificar sesiones
            raise RuntimeError("JWT_SECRET es demasiado corto: en producción usa una frase aleatoria de al menos 32 caracteres")
        logger.warning("JWT_SECRET es demasiado corto: usa una frase aleatoria de al menos 32 caracteres")
    if COOKIE_SECURE and os.environ.get("ADMIN_PASSWORD", "admin123") == "admin123":
        logger.warning("ADMIN_PASSWORD sigue siendo la de ejemplo: cámbiala en un servidor público")

    # Los datos de ejemplo (cajero, productos, socios) se crean solo en el primer arranque de una base
    # vacía: si luego se borran, no reaparecen con contraseñas conocidas.
    first_boot = await db.users.count_documents({}) == 0 and not await db.settings.find_one({"key": "seeded"})
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@weedlemon.es").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None and (first_boot or not await db.users.find_one({"role": "admin"})):
        await db.users.insert_one({
            "name": "Administrador", "email": admin_email, "role": "admin",
            "password_hash": hash_password(admin_password), "status": "activa",
            "created_at": now_utc()})
        logger.info("Admin creado: %s", admin_email)
    elif existing is not None and os.environ.get("ADMIN_RESET_PASSWORD", "").lower() == "true":
        # Solo si se pide expresamente (p. ej. contraseña olvidada): ya no se reescribe en cada arranque
        await db.users.update_one({"_id": existing["_id"]}, {"$set": {"password_hash": hash_password(admin_password)}})
        logger.warning("Contraseña del administrador restablecida desde ADMIN_PASSWORD")

    if first_boot and not await db.users.find_one({"email": "cajero@weedlemon.es"}):
        await db.users.insert_one({
            "name": "Carmen Ruiz", "email": "cajero@weedlemon.es", "role": "cajero",
            "password_hash": hash_password("cajero123"), "status": "activa",
            "created_at": now_utc()})

    if first_boot and await db.products.count_documents({}) == 0:
        for p in SEED_PRODUCTS:
            p["created_at"] = now_utc()
            await db.products.insert_one(p)
        logger.info("Productos de ejemplo cargados")

    if first_boot and await db.users.count_documents({"role": "socio"}) == 0:
        for s in SEED_SOCIOS:
            n = await next_seq("member")
            await db.users.insert_one({**s, "role": "socio", "status": "activa",
                                       "member_number": f"WL-{n:04d}", "created_at": now_utc()})
        logger.info("Socios de ejemplo cargados")

    await db.users.update_many({"role": "socio", "balance": {"$exists": False}}, {"$set": {"balance": 0.0}})
    for name, url in PRODUCT_IMAGES.items():
        await db.products.update_one({"name": name, "image_url": {"$exists": False}}, {"$set": {"image_url": url}})

    if await db.categories.count_documents({}) == 0:
        for c in DEFAULT_CATEGORIES:
            await db.categories.insert_one({**c, "created_at": now_utc()})
        logger.info("Categorías por defecto creadas")

    await db.settings.update_one({"key": "seeded"}, {"$setOnInsert": {"key": "seeded", "at": now_utc()}}, upsert=True)
    await seed_food_and_drinks()
    await migrate()
    try:
        await db.cash_sessions.create_index("active_lock", unique=True, sparse=True)
    except Exception as e:  # p. ej. dos turnos activos heredados: se avisa y se sigue arrancando
        logger.error("No se pudo crear el índice de turno único: %s", e)

    await db.password_resets.create_index("token_hash")
    await db.password_resets.create_index([("user_id", 1), ("created_at", -1)])
    await db.password_resets.create_index("expires_at", expireAfterSeconds=86400)  # se borran un día después de caducar
    if not email_provider():
        (logger.error if COOKIE_SECURE else logger.info)(
            "Correo sin configurar: la recuperación de contraseña no enviará emails (configura BREVO_API_KEY o SMTP_HOST)")
    await db.revoked_tokens.create_index("jti")
    await db.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)  # MongoDB los borra al caducar
    if STORAGE_MODE == "mongo":
        await db.file_blobs.create_index("path", unique=True)
        logger.info("Archivos guardados en MongoDB (colección file_blobs)")
        return
    if STORAGE_MODE == "local":
        logger.info("Almacenamiento local de archivos en %s", LOCAL_STORAGE_DIR)
        return
    try:
        init_storage()
        logger.info("Storage inicializado")
    except Exception as e:
        logger.error("Storage init falló: %s", e)


app.include_router(api_router)

# ---------- frontend compilado ----------
# Si existe frontend/build (o FRONTEND_BUILD_DIR), la app y la API salen de la misma web: sin CORS ni cookies
# de terceros, que Safari y otros navegadores bloquean. Lo usa el Dockerfile.
FRONTEND_BUILD = Path(os.environ.get("FRONTEND_BUILD_DIR") or Path(__file__).resolve().parent.parent / "frontend" / "build").resolve()
if (FRONTEND_BUILD / "index.html").is_file():
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_app(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="No encontrado")
        target = (FRONTEND_BUILD / full_path).resolve()
        if full_path and target.is_file() and FRONTEND_BUILD in target.parents:
            cache = "public, max-age=31536000, immutable" if full_path.startswith("static/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(FRONTEND_BUILD / "index.html", headers={"Cache-Control": "no-cache"})  # rutas de la app (/tpv, /caja…)

class SecurityMiddleware:
    """Protección CSRF y cabeceras de seguridad para toda la API.

    - CSRF: en producción las cookies de sesión van con SameSite=None, así que otra web podría intentar
      lanzar peticiones con la sesión del usuario. Toda petición que modifica datos debe llevar la
      cabecera X-Requested-With (la pone el frontend); un navegador no deja que otra web la añada
      sin pasar por CORS, que solo admite el origen del frontend.
    - Cabeceras: nosniff, sin iframes, sin enviar la URL a terceros.
    """
    UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
    HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"camera=(self), microphone=(), geolocation=()"),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["method"] in self.UNSAFE and scope["path"].startswith("/api/"):
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            if headers.get(b"x-requested-with", b"").lower() != b"xmlhttprequest":
                body = '{"detail":"Petición rechazada: falta la cabecera de seguridad (CSRF)"}'.encode("utf-8")
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())] + self.HEADERS})
                await send({"type": "http.response.body", "body": body})
                return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [h for h in self.HEADERS if h[0] not in existing]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def allowed_origins():
    origins = [os.environ.get("FRONTEND_URL", "http://localhost:3000")]
    if not COOKIE_SECURE:  # modo local
        origins.append("http://localhost:3000")
    return sorted(set(origins))


# Orden: el último añadido es el más externo. CORS va fuera para que también los rechazos lleven sus cabeceras.
app.add_middleware(SecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With", "Authorization"],
)
