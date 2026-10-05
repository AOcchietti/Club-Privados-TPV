from dotenv import load_dotenv
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

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI()
api_router = APIRouter(prefix="/api")

JWT_ALGORITHM = "HS256"
MADRID = ZoneInfo("Europe/Madrid")
STAFF_ROLES = ["admin", "cajero"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("weedlemon")


# ---------- helpers ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {"sub": user_id, "email": email, "role": role, "type": "access",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=60 * 8)}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


# En producción (https) las cookies van Secure + SameSite=None. En local (http://localhost)
# se pone COOKIE_SECURE=false en el .env y pasan a SameSite=Lax.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").strip().lower() not in ("false", "0", "no")
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


async def log_activity(actor: dict, action: str, details: str):
    await db.activity.insert_one({
        "user_id": actor.get("id") or actor.get("_id"),
        "user_name": actor.get("name", "Sistema"),
        "user_role": actor.get("role", "-"),
        "action": action,
        "details": details,
        "created_at": now_utc(),
    })


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
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
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
DOC_TYPES = ["DNI", "NIE", "Pasaporte", "Otro"]


async def get_active_session():
    return await db.cash_sessions.find_one({"status": {"$in": ACTIVE_STATUSES}})


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Elemento no encontrado")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
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


# Sin EMERGENT_LLM_KEY (por ejemplo en local) los archivos se guardan en disco, en backend/uploads/
# o en la carpeta indicada en LOCAL_STORAGE_DIR.
STORAGE_MODE = "emergent" if (os.environ.get("EMERGENT_LLM_KEY") or "").strip() else "local"
LOCAL_STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR") or Path(__file__).parent / "uploads").resolve()


def local_path(path: str) -> Path:
    target = (LOCAL_STORAGE_DIR / path).resolve()
    if LOCAL_STORAGE_DIR not in target.parents:
        raise HTTPException(status_code=400, detail="Ruta de archivo no válida")
    return target


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if STORAGE_MODE == "local":
        target = local_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": path, "size": len(data)}
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    if STORAGE_MODE == "local":
        target = local_path(path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


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
    version: int


class CashMovementIn(BaseModel):
    type: str  # "in" | "out"
    amount: float
    reason: str


# ---------- auth ----------

@api_router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    email = body.email.strip().lower()
    identifier = f"{request.client.host}:{email}"
    attempt = await db.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("count", 0) >= 5:
        locked_until = attempt.get("locked_until")
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
    access = create_access_token(str(user["_id"]), email, user["role"])
    refresh = create_refresh_token(str(user["_id"]))
    set_auth_cookies(response, access, refresh)
    out = ser(user)
    out["token"] = access
    await log_activity(out, "login", f"{out['name']} inició sesión")
    return out


@api_router.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    await log_activity(user, "logout", f"{user['name']} cerró sesión")
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
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    access = create_access_token(str(user["_id"]), user["email"], user["role"])
    set_access_cookie(response, access)
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
            updates["password_hash"] = hash_password(data["password"])
    if not updates:
        return ser(target)
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    await log_activity(user, "usuario_editado", f"Editado «{target['name']}»: {', '.join(updates.keys())}")
    return ser(await db.users.find_one({"_id": ObjectId(user_id)}))


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    await db.users.delete_one({"_id": ObjectId(user_id)})
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
    if not session:
        raise HTTPException(status_code=400, detail="Abre un turno en Caja para recargar: el efectivo tiene que entrar en un turno")
    if session["status"] != "open":
        raise HTTPException(status_code=400, detail=f"La caja está {STATUS_TEXT[session['status']]}: las recargas están en pausa")
    amount = round(body.amount, 2)
    await db.users.update_one({"_id": target["_id"]}, {"$inc": {"balance": amount}})
    await db.recharges.insert_one({
        "socio_id": user_id,
        "socio_name": target["name"],
        "amount": amount,
        "method": "efectivo",
        "session_id": str(session["_id"]),
        "created_by": user["name"],
        "created_at": now_utc(),
    })
    await log_activity(user, "recarga", f"Recarga de {amount} Cr (efectivo) para {target['name']}")
    return ser(await db.users.find_one({"_id": target["_id"]}))


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
    result = put_object(path, data, content_type)
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


async def read_image_upload(file: UploadFile, max_mb: int = 5) -> bytes:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes")
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"La imagen no puede superar {max_mb} MB")
    return data


@api_router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(require_staff)):
    data = await read_image_upload(file)
    path = await store_file(data, file.content_type or "image/jpeg", file.filename, f"uploads/{user['id']}", user["id"])
    await log_activity(user, "foto_subida", f"Foto subida: {file.filename}")
    return {"path": path}


# ---------- alta pública de socios (formulario QR, sin login) ----------

@api_router.post("/public/upload")
async def public_upload(request: Request, file: UploadFile = File(...)):
    await rate_limit(request, "public_upload", limit=120)
    data = await read_image_upload(file, max_mb=8)
    path = await store_file(data, file.content_type or "image/jpeg", file.filename, "kyc", "formulario_publico", public=True)
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
    data, _ = get_object(legal["path"])
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="acuerdo-legal-weed-lemon.pdf"'})


@api_router.post("/settings/legal-pdf")
async def upload_legal_pdf(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="El archivo tiene que ser un PDF")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El PDF no puede superar 10 MB")
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
    data, content_type = get_object(path)
    return Response(content=data, media_type=record.get("content_type") or content_type)


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


@api_router.get("/categories")
async def list_categories(user: dict = Depends(require_staff)):
    docs = await db.categories.find().sort("label", 1).to_list(100)
    return [ser(d) for d in docs]


@api_router.post("/categories")
async def create_category(body: CategoryIn, user: dict = Depends(require_staff)):
    key = slugify(body.label)
    if not key:
        raise HTTPException(status_code=400, detail="Nombre no válido")
    if await db.categories.find_one({"key": key}):
        raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
    doc = {"key": key, "label": body.label.strip(), "color": body.color, "created_at": now_utc()}
    result = await db.categories.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "categoria_creada", f"Nueva categoría «{doc['label']}»")
    return ser(doc)


@api_router.patch("/categories/{cat_id}")
async def update_category(cat_id: str, body: CategoryIn, user: dict = Depends(require_staff)):
    target = await db.categories.find_one({"_id": ObjectId(cat_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    await db.categories.update_one({"_id": ObjectId(cat_id)}, {"$set": {"label": body.label.strip(), "color": body.color}})
    await log_activity(user, "categoria_editada", f"Categoría «{body.label}» actualizada")
    return ser(await db.categories.find_one({"_id": ObjectId(cat_id)}))


@api_router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, user: dict = Depends(require_staff)):
    target = await db.categories.find_one({"_id": ObjectId(cat_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
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
    if category:
        query["category"] = category
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    docs = await db.products.find(query).sort("name", 1).to_list(500)
    return [ser(d) for d in docs]


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
        query["stock"] = {"$gte": -delta - 1e-9}
    res = await db.products.update_one(query, {"$inc": {"stock": delta}})
    if res.modified_count == 0:
        raise HTTPException(status_code=400, detail="El stock no puede quedar en negativo")
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
    docs = await db.sales.find({"out_of_shift": True, "out_of_shift_pending": True}).to_list(5000)
    return {"count": len(docs), "total": round(sum(s["total"] for s in docs), 2)}


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
    if not out_of_shift:
        for item in body.items:
            await db.products.update_one({"_id": oid(item.product_id)}, {"$inc": {"stock": -round(item.qty, 3)}})
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

# Orden de las secciones del recuento según palabras clave de la categoría (válido para cualquier club):
# flores primero, después hachís, extractos, dry y polen, y al final el resto en orden alfabético.
SECTION_PRIORITY = [("flor", "marihuana", "marijuana"), ("hash", "hachis"), ("extracto",), ("dry",), ("polen",)]


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()


def section_sort_key(label: str):
    t = plain(label)
    for rank, words in enumerate(SECTION_PRIORITY):
        if any(w in t for w in words):
            return (rank, t)
    return (len(SECTION_PRIORITY), t)


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
    cats = {c["key"]: c["label"] for c in await db.categories.find().to_list(500)}
    products = await db.products.find({"$or": [{"active": True}, {"stock": {"$gt": 0}}]}).sort("name", 1).to_list(5000)
    lines = []
    for p in products:
        lines.append({
            "product_id": str(p["_id"]),
            "name": p["name"],
            "unit": p.get("unit", "g"),
            "category": p.get("category"),
            "category_label": cats.get(p.get("category"), p.get("category") or "Sin categoría"),
            "expected": round(p.get("stock", 0) or 0, 3),
            "counted": None,
            "difference": None,
        })
    lines.sort(key=lambda l: (section_sort_key(l["category_label"]), plain(l["name"])))
    doc = {
        "session_id": str(session["_id"]),
        "kind": kind,
        "status": "draft",
        "scope": STOCKTAKE_SCOPE,
        "sections": sorted({l["category_label"] for l in lines}, key=section_sort_key),
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
    absorbed = {
        "out_of_shift_count": len(pending),
        "out_of_shift_total": round(sum(s["total"] for s in pending), 2),
        "out_of_shift_sale_ids": [str(s["_id"]) for s in pending],
    }
    await db.cash_sessions.update_one({"_id": doc["_id"]}, {"$set": absorbed})
    doc.update(absorbed)
    await build_stocktake(doc, "opening", user)
    extra = f" · {absorbed['out_of_shift_count']} ventas fuera de turno incorporadas ({absorbed['out_of_shift_total']} Cr)" if pending else ""
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
    await db.stocktakes.update_many({"session_id": str(session["_id"]), "status": "draft"},
                                    {"$set": {"status": "cancelled", "cancelled_at": now_utc(), "cancelled_by": user["name"]}})
    await db.cash_sessions.update_one({"_id": session["_id"]}, {
        "$set": {"status": "cancelled", "cancelled_at": now_utc(), "cancelled_by": user["name"]},
        "$unset": {"active_lock": ""}})
    await log_activity(user, "caja_apertura_cancelada",
                       f"Apertura del turno de {session['opened_by']} cancelada por administración · "
                       f"{len(sales)} ventas fuera de turno vuelven a pendientes")
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
    lines = st["lines"]
    line = next((l for l in lines if l["product_id"] == body.product_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Ese producto no está en el recuento")
    set_counted(line, body.counted)
    return await save_stocktake_lines(st, lines, body.version)


@api_router.post("/cash/stocktake/autofill")
async def cash_stocktake_autofill(body: AutofillIn, user: dict = Depends(require_staff)):
    session = await require_session(user, "opening", "closing")
    st = await get_draft_stocktake(session)
    if not st:
        raise HTTPException(status_code=400, detail="No hay ningún recuento en curso")
    if not body.section and not body.product_id:
        raise HTTPException(status_code=400, detail="Indica una sección o un producto")
    lines = st["lines"]
    touched = 0
    for l in lines:
        if (body.section and l["category_label"] == body.section) or (body.product_id and l["product_id"] == body.product_id):
            set_counted(l, l["expected"])
            touched += 1
    if not touched:
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
    return {
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
    pdf = build_closing_pdf(session, sales, recharges, movements, opening, closing)
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
    return {"message": "Weed Lemon Social Club POS API"}


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


@app.on_event("startup")
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

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@weedlemon.es").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "name": "Administrador", "email": admin_email, "role": "admin",
            "password_hash": hash_password(admin_password), "status": "activa",
            "created_at": now_utc()})
        logger.info("Admin creado: %s", admin_email)
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})

    if not await db.users.find_one({"email": "cajero@weedlemon.es"}):
        await db.users.insert_one({
            "name": "Carmen Ruiz", "email": "cajero@weedlemon.es", "role": "cajero",
            "password_hash": hash_password("cajero123"), "status": "activa",
            "created_at": now_utc()})

    if await db.products.count_documents({}) == 0:
        for p in SEED_PRODUCTS:
            p["created_at"] = now_utc()
            await db.products.insert_one(p)
        logger.info("Productos de ejemplo cargados")

    if await db.users.count_documents({"role": "socio"}) == 0:
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

    await migrate()
    try:
        await db.cash_sessions.create_index("active_lock", unique=True, sparse=True)
    except Exception as e:  # p. ej. dos turnos activos heredados: se avisa y se sigue arrancando
        logger.error("No se pudo crear el índice de turno único: %s", e)

    if STORAGE_MODE == "local":
        logger.info("Almacenamiento local de archivos en %s", LOCAL_STORAGE_DIR)
        return
    try:
        init_storage()
        logger.info("Storage inicializado")
    except Exception as e:
        logger.error("Storage init falló: %s", e)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000"), "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
