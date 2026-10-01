from dotenv import load_dotenv
load_dotenv()

import os
import logging
import uuid
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from zoneinfo import ZoneInfo

import bcrypt
import jwt
import requests
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends, Query, UploadFile, File
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

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


def set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none", max_age=60 * 60 * 8, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none", max_age=604800, path="/")


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


async def get_open_session():
    return await db.cash_sessions.find_one({"status": "open"})


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


def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


# ---------- schemas ----------

class LoginIn(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    name: str
    role: str = "socio"
    email: Optional[str] = None
    password: Optional[str] = None
    dni: Optional[str] = None
    phone: Optional[str] = None
    status: str = "activa"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    dni: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None


class ProductIn(BaseModel):
    name: str
    category: str
    price: float
    unit: str = "g"
    stock: float = 0
    thc: Optional[float] = None
    cbd: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    active: bool = True


class SaleItemIn(BaseModel):
    product_id: str
    qty: float


class SaleCreate(BaseModel):
    items: List[SaleItemIn]
    payment_method: str = "efectivo"
    socio_id: Optional[str] = None


class CashOpenIn(BaseModel):
    starting_amount: float = 0


class CashCloseIn(BaseModel):
    counted_amount: float = 0
    notes: Optional[str] = None


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
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none", max_age=60 * 60 * 8, path="/")
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
        query["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                        {"dni": {"$regex": q, "$options": "i"}},
                        {"member_number": {"$regex": q, "$options": "i"}},
                        {"email": {"$regex": q, "$options": "i"}}]
    docs = await db.users.find(query).sort("created_at", -1).to_list(500)
    return [ser(d) for d in docs]


@api_router.post("/users")
async def create_user(body: UserCreate, user: dict = Depends(require_staff)):
    if body.role not in ["admin", "cajero", "socio"]:
        raise HTTPException(status_code=400, detail="Rol no válido")
    if user["role"] != "admin" and body.role != "socio":
        raise HTTPException(status_code=403, detail="Solo el administrador puede crear miembros del equipo")
    doc = {
        "name": body.name.strip(),
        "role": body.role,
        "email": body.email.strip().lower() if body.email else None,
        "dni": body.dni,
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
        n = await next_seq("member")
        doc["member_number"] = f"WL-{n:04d}"
        doc["balance"] = 0.0
        if doc["email"] and await db.users.find_one({"email": doc["email"], "role": {"$ne": "socio"}}):
            raise HTTPException(status_code=400, detail="Ese email pertenece a un miembro del equipo")
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "usuario_creado", f"Alta de {body.role} «{doc['name']}»")
    return ser(doc)


@api_router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, user: dict = Depends(require_staff)):
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user["role"] != "admin" and target.get("role") != "socio":
        raise HTTPException(status_code=403, detail="Solo el administrador puede editar el equipo")
    updates = {}
    data = body.model_dump(exclude_none=True)
    for k in ["name", "dni", "phone", "status"]:
        if k in data:
            updates[k] = data[k]
    if "email" in data and data["email"]:
        updates["email"] = data["email"].strip().lower()
    if user["role"] == "admin":
        if "role" in data:
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
    doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return ser(doc)


@api_router.post("/users/{user_id}/recharge")
async def recharge_balance(user_id: str, body: RechargeIn, user: dict = Depends(require_staff)):
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target or target.get("role") != "socio":
        raise HTTPException(status_code=404, detail="Socio no encontrado")
    if body.amount <= 0 or body.amount > 1000:
        raise HTTPException(status_code=400, detail="Importe no válido (máx. 1000 € por recarga)")
    if body.method not in ["efectivo", "tarjeta"]:
        raise HTTPException(status_code=400, detail="Método de pago no válido")
    session = await get_open_session()
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"balance": round(body.amount, 2)}})
    await db.recharges.insert_one({
        "socio_id": user_id,
        "socio_name": target["name"],
        "amount": round(body.amount, 2),
        "method": body.method,
        "session_id": str(session["_id"]) if session else None,
        "created_by": user["name"],
        "created_at": now_utc(),
    })
    await log_activity(user, "recarga", f"Recarga de {round(body.amount, 2)}€ ({body.method}) para {target['name']}")
    return ser(await db.users.find_one({"_id": ObjectId(user_id)}))


@api_router.get("/users/{user_id}/recharges")
async def list_recharges(user_id: str, user: dict = Depends(require_staff)):
    docs = await db.recharges.find({"socio_id": user_id}).sort("created_at", -1).to_list(200)
    return [ser(d) for d in docs]


# ---------- uploads (object storage) ----------

@api_router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(require_staff)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="La imagen no puede superar 5 MB")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    path = f"{APP_NAME}/uploads/{user['id']}/{uuid.uuid4()}.{ext}"
    result = put_object(path, data, file.content_type or "image/jpeg")
    await db.files.insert_one({
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": file.content_type,
        "size": result["size"],
        "is_deleted": False,
        "created_by": user["id"],
        "created_at": now_utc(),
    })
    await log_activity(user, "foto_subida", f"Foto subida: {file.filename}")
    return {"path": result["path"]}


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


@api_router.post("/products")
async def create_product(body: ProductIn, user: dict = Depends(require_staff)):
    doc = body.model_dump()
    doc["created_at"] = now_utc()
    result = await db.products.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "producto_creado", f"Nuevo producto «{doc['name']}» ({doc['price']} créditos/{doc['unit']})")
    return ser(doc)


@api_router.patch("/products/{product_id}")
async def update_product(product_id: str, body: ProductIn, user: dict = Depends(require_staff)):
    target = await db.products.find_one({"_id": ObjectId(product_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    await db.products.update_one({"_id": ObjectId(product_id)}, {"$set": body.model_dump()})
    await log_activity(user, "producto_editado", f"Editado «{body.name}» (stock {body.stock}{body.unit}, {body.price} créditos)")
    return ser(await db.products.find_one({"_id": ObjectId(product_id)}))


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

@api_router.post("/sales")
async def create_sale(body: SaleCreate, user: dict = Depends(require_staff)):
    if not body.items:
        raise HTTPException(status_code=400, detail="El carrito está vacío")
    lines = []
    total = 0.0
    for item in body.items:
        if item.qty <= 0:
            raise HTTPException(status_code=400, detail="Cantidad no válida")
        product = await db.products.find_one({"_id": ObjectId(item.product_id)})
        if not product or not product.get("active", True):
            raise HTTPException(status_code=400, detail="Producto no disponible")
        if product.get("stock", 0) < item.qty:
            raise HTTPException(status_code=400, detail=f"Stock insuficiente de «{product['name']}» (quedan {product.get('stock', 0)}{product['unit']})")
        line_total = round(product["price"] * item.qty, 2)
        total += line_total
        lines.append({
            "product_id": item.product_id,
            "name": product["name"],
            "category": product["category"],
            "unit": product["unit"],
            "price": product["price"],
            "qty": item.qty,
            "line_total": line_total,
        })
    socio = None
    if body.socio_id:
        socio = await db.users.find_one({"_id": ObjectId(body.socio_id), "role": "socio"})
    if not socio:
        raise HTTPException(status_code=400, detail="Asigna un socio para cobrar desde su saldo")
    for item in body.items:
        await db.products.update_one({"_id": ObjectId(item.product_id)}, {"$inc": {"stock": -item.qty}})
    await db.users.update_one({"_id": socio["_id"]}, {"$inc": {"balance": -round(total, 2)}})
    session = await get_open_session()
    ticket = await next_seq("ticket")
    sale = {
        "ticket_number": f"T-{ticket:05d}",
        "items": lines,
        "total": round(total, 2),
        "payment_method": "saldo",
        "socio_id": str(socio["_id"]) if socio else None,
        "socio_name": socio["name"] if socio else None,
        "socio_member_number": socio.get("member_number") if socio else None,
        "cajero_id": user["id"],
        "cajero_name": user["name"],
        "cash_session_id": str(session["_id"]) if session else None,
        "created_at": now_utc(),
    }
    result = await db.sales.insert_one(sale)
    sale["_id"] = result.inserted_id
    new_balance = round((socio.get("balance") or 0) - sale["total"], 2)
    nota = f" · saldo resultante {new_balance} Cr" + (" (DEUDA)" if new_balance < 0 else "")
    await log_activity(user, "venta", f"Ticket {sale['ticket_number']} · {sale['total']} Cr del saldo de {socio['name']}{nota}")
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

async def session_totals(session):
    start = session["opened_at"]
    sales = await db.sales.find({"created_at": {"$gte": start}}).to_list(1000)
    efectivo = sum(s["total"] for s in sales if s["payment_method"] == "efectivo")
    tarjeta = sum(s["total"] for s in sales if s["payment_method"] == "tarjeta")
    recharges = await db.recharges.find({"created_at": {"$gte": start}}).to_list(500)
    rec_efectivo = sum(r["amount"] for r in recharges if r["method"] == "efectivo")
    rec_tarjeta = sum(r["amount"] for r in recharges if r["method"] == "tarjeta")
    efectivo += rec_efectivo
    tarjeta += rec_tarjeta
    ventas_saldo = round(sum(s["total"] for s in sales if s["payment_method"] == "saldo"), 2)
    neg = await db.users.find({"role": "socio", "balance": {"$lt": 0}}).to_list(1000)
    deuda = round(sum(-(u.get("balance") or 0) for u in neg), 2)
    movements = await db.cash_movements.find({"session_id": str(session["_id"])}).sort("created_at", -1).to_list(200)
    entradas = sum(m["amount"] for m in movements if m["type"] == "in")
    salidas = sum(m["amount"] for m in movements if m["type"] == "out")
    esperado = session["starting_amount"] + efectivo + entradas - salidas
    return {
        "ventas_count": len(sales),
        "efectivo": round(efectivo, 2),
        "tarjeta": round(tarjeta, 2),
        "recargas": round(rec_efectivo + rec_tarjeta, 2),
        "ventas_saldo": ventas_saldo,
        "deuda_socios": deuda,
        "entradas": round(entradas, 2),
        "salidas": round(salidas, 2),
        "esperado": round(esperado, 2),
        "movements": [ser(m) for m in movements],
    }


@api_router.get("/cash/current")
async def cash_current(user: dict = Depends(require_staff)):
    session = await get_open_session()
    if not session:
        return {"session": None}
    totals = await session_totals(session)
    return {"session": ser(session), "totals": totals}


@api_router.post("/cash/open")
async def cash_open(body: CashOpenIn, user: dict = Depends(require_admin)):
    if await get_open_session():
        raise HTTPException(status_code=400, detail="Ya hay una caja abierta")
    doc = {
        "opened_by": user["name"],
        "opened_by_id": user["id"],
        "opened_at": now_utc(),
        "starting_amount": body.starting_amount,
        "status": "open",
    }
    result = await db.cash_sessions.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "caja_abierta", f"Caja abierta con {body.starting_amount} créditos de fondo")
    return ser(doc)


@api_router.post("/cash/close")
async def cash_close(body: CashCloseIn, user: dict = Depends(require_admin)):
    session = await get_open_session()
    if not session:
        raise HTTPException(status_code=400, detail="No hay ninguna caja abierta")
    totals = await session_totals(session)
    diff = round(body.counted_amount - totals["esperado"], 2)
    await db.cash_sessions.update_one({"_id": session["_id"]}, {"$set": {
        "status": "closed",
        "closed_by": user["name"],
        "closed_at": now_utc(),
        "counted_amount": body.counted_amount,
        "expected_amount": totals["esperado"],
        "difference": diff,
        "notes": body.notes,
        "totals": {k: v for k, v in totals.items() if k != "movements"},
    }})
    await log_activity(user, "caja_cerrada", f"Caja cerrada · esperado {totals['esperado']}, contado {body.counted_amount} (diferencia {diff})")
    return ser(await db.cash_sessions.find_one({"_id": session["_id"]}))


@api_router.post("/cash/movements")
async def cash_movement(body: CashMovementIn, user: dict = Depends(require_admin)):
    session = await get_open_session()
    if not session:
        raise HTTPException(status_code=400, detail="Abre la caja primero")
    if body.type not in ["in", "out"] or body.amount <= 0:
        raise HTTPException(status_code=400, detail="Movimiento no válido")
    doc = {
        "session_id": str(session["_id"]),
        "type": body.type,
        "amount": body.amount,
        "reason": body.reason.strip(),
        "created_by": user["name"],
        "created_at": now_utc(),
    }
    result = await db.cash_movements.insert_one(doc)
    doc["_id"] = result.inserted_id
    await log_activity(user, "movimiento_caja", f"{'Entrada' if body.type == 'in' else 'Salida'} de {body.amount} créditos · {body.reason}")
    return ser(doc)


@api_router.get("/cash/sessions")
async def cash_sessions(user: dict = Depends(require_admin)):
    docs = await db.cash_sessions.find({"status": "closed"}).sort("opened_at", -1).to_list(100)
    return [ser(d) for d in docs]


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
    {"name": "Lucía Fernández", "dni": "45678901L", "phone": "612345678", "email": "lucia.fernandez@example.com"},
    {"name": "Marco Ibáñez", "dni": "23456789M", "phone": "623456789", "email": "marco.ibanez@example.com"},
    {"name": "Sara Delgado", "dni": "34567890S", "phone": "634567890", "email": None},
]


@app.on_event("startup")
async def startup():
    await db.users.create_index("email")
    await db.products.create_index("name")
    await db.sales.create_index("created_at")
    await db.activity.create_index("created_at")
    await db.login_attempts.create_index("identifier")

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
