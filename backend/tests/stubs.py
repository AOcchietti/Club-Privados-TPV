"""Sustitutos en memoria de fastapi / motor / bson / pymongo / bcrypt / segno.

Permiten ejecutar las pruebas de backend/tests sin MongoDB ni servidor: se importan las
funciones reales de server.py y se llaman directamente. La base de datos es un MongoDB
en memoria que implementa los operadores que usa la aplicación.
"""
import copy
import itertools
import re
import sys
import types


# ---------------- bson ----------------
class InvalidId(Exception):
    pass


class ObjectId:
    _counter = itertools.count(1)

    def __init__(self, v=None):
        if v is None:
            self._s = f"{next(ObjectId._counter):024x}"
        elif isinstance(v, ObjectId):
            self._s = v._s
        elif isinstance(v, str) and re.fullmatch(r"[0-9a-f]{24}", v):
            self._s = v
        else:
            raise InvalidId(f"invalid id {v!r}")

    def __str__(self):
        return self._s

    __repr__ = __str__

    def __eq__(self, o):
        return isinstance(o, ObjectId) and o._s == self._s

    def __hash__(self):
        return hash(self._s)

    def __lt__(self, o):
        return self._s < o._s


bson = types.ModuleType("bson")
bson.ObjectId = ObjectId
bson_errors = types.ModuleType("bson.errors")
bson_errors.InvalidId = InvalidId
bson.errors = bson_errors
sys.modules["bson"] = bson
sys.modules["bson.errors"] = bson_errors


# ---------------- pymongo ----------------
class DuplicateKeyError(Exception):
    pass


pymongo = types.ModuleType("pymongo")
pymongo_errors = types.ModuleType("pymongo.errors")
pymongo_errors.DuplicateKeyError = DuplicateKeyError
pymongo.errors = pymongo_errors
sys.modules["pymongo"] = pymongo
sys.modules["pymongo.errors"] = pymongo_errors


# ---------------- in-memory mongo ----------------
MISSING = object()


def _naive(v):
    import datetime as _dt
    if isinstance(v, _dt.datetime) and v.tzinfo is not None:
        return v.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return v


def _cmp_ok(val, op, arg):
    if val is MISSING or val is None:
        return False
    val, arg = _naive(val), _naive(arg)
    try:
        return {"$gte": val >= arg, "$gt": val > arg, "$lt": val < arg, "$lte": val <= arg}[op]
    except TypeError:
        return False


def match(doc, q):
    for k, cond in q.items():
        if k == "$or":
            if not any(match(doc, c) for c in cond):
                return False
            continue
        val = doc.get(k, MISSING)
        if isinstance(cond, dict) and cond and all(str(op).startswith("$") for op in cond):
            for op, arg in cond.items():
                v = None if val is MISSING else val
                if op == "$in":
                    ok = v in arg
                elif op == "$nin":
                    ok = v not in arg
                elif op == "$exists":
                    ok = (val is not MISSING) == bool(arg)
                elif op in ("$gte", "$gt", "$lt", "$lte"):
                    ok = _cmp_ok(val, op, arg)
                elif op == "$ne":
                    ok = v != arg
                elif op == "$regex":
                    flags = re.I if "i" in cond.get("$options", "") else 0
                    ok = isinstance(v, str) and re.search(arg, v, flags) is not None
                elif op == "$options":
                    ok = True
                else:
                    raise NotImplementedError(op)
                if not ok:
                    return False
        else:
            if cond is None:
                if val is not MISSING and val is not None:
                    return False
            elif val is MISSING or val != cond:
                return False
    return True


def apply_update(doc, upd, inserting=False):
    for op, fields in upd.items():
        for k, v in fields.items():
            if op == "$setOnInsert":
                if inserting:
                    doc[k] = _strip_tz(copy.deepcopy(v))
            elif op == "$set":
                doc[k] = _strip_tz(copy.deepcopy(v))
            elif op == "$inc":
                doc[k] = doc.get(k, 0) + v
            elif op == "$unset":
                doc.pop(k, None)
            else:
                raise NotImplementedError(op)


def _strip_tz(v):
    import datetime as _dt
    if isinstance(v, _dt.datetime) and v.tzinfo is not None:
        return v.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    if isinstance(v, dict):
        return {k: _strip_tz(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_strip_tz(x) for x in v]
    return v


class Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self.docs.sort(key=lambda x: (x.get(k) is not None, x.get(k) if x.get(k) is not None else 0),
                           reverse=(d == -1))
        return self

    async def to_list(self, n):
        return [copy.deepcopy(d) for d in self.docs[:n]]


class Collection:
    def __init__(self):
        self.docs = []
        self.unique = []

    async def create_index(self, key, unique=False, sparse=False, **kw):
        if unique:
            field = key if isinstance(key, str) else key[0][0]
            vals = [d[field] for d in self.docs if field in d]
            if len(vals) != len(set(map(str, vals))):
                raise DuplicateKeyError(field)
            self.unique.append(field)

    def _check_unique(self, doc, exclude=None):
        for f in self.unique:
            if f in doc and any(d is not exclude and d.get(f, MISSING) == doc[f] for d in self.docs):
                raise DuplicateKeyError(f)

    async def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self._check_unique(doc)
        self.docs.append(_strip_tz(copy.deepcopy(doc)))
        return Result(inserted_id=doc["_id"])

    async def find_one(self, q=None, *a, **kw):
        for d in self.docs:
            if match(d, q or {}):
                return copy.deepcopy(d)
        return None

    def find(self, q=None, *a, **kw):
        return Cursor([d for d in self.docs if match(d, q or {})])

    async def count_documents(self, q):
        return len([d for d in self.docs if match(d, q)])

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if match(d, q):
                before = copy.deepcopy(d)
                apply_update(d, upd)
                self._check_unique(d, exclude=d)
                return Result(matched_count=1, modified_count=int(before != d))
        if upsert:
            new = {k: v for k, v in q.items() if not isinstance(v, dict) and not k.startswith("$")}
            apply_update(new, upd, inserting=True)
            await self.insert_one(new)
            return Result(matched_count=0, modified_count=0, upserted_id=new["_id"])
        return Result(matched_count=0, modified_count=0)

    async def update_many(self, q, upd):
        n = 0
        for d in self.docs:
            if match(d, q):
                apply_update(d, upd)
                n += 1
        return Result(matched_count=n, modified_count=n)

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if match(d, q):
                del self.docs[i]
                return Result(deleted_count=1)
        return Result(deleted_count=0)

    async def delete_many(self, q):
        before = len(self.docs)
        self.docs[:] = [d for d in self.docs if not match(d, q)]
        return Result(deleted_count=before - len(self.docs))

    async def find_one_and_update(self, q, upd, upsert=False, return_document=False):
        for d in self.docs:
            if match(d, q):
                apply_update(d, upd)
                return copy.deepcopy(d)
        if upsert:
            new = {k: v for k, v in q.items() if not isinstance(v, dict)}
            apply_update(new, upd, inserting=True)
            await self.insert_one(new)
            return copy.deepcopy(new)
        return None


class DB:
    def __init__(self):
        self.cols = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self.cols.setdefault(name, Collection())

    __getitem__ = __getattr__


class AsyncIOMotorClient:
    def __init__(self, *a, **kw):
        self.dbs = {}

    def __getitem__(self, name):
        return self.dbs.setdefault(name, DB())

    def close(self):
        pass


motor = types.ModuleType("motor")
motor_asyncio = types.ModuleType("motor.motor_asyncio")
motor_asyncio.AsyncIOMotorClient = AsyncIOMotorClient
motor.motor_asyncio = motor_asyncio
sys.modules["motor"] = motor
sys.modules["motor.motor_asyncio"] = motor_asyncio


# ---------------- fastapi ----------------
class HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


class Request:
    def __init__(self, ip="1.2.3.4", headers=None, cookies=None):
        self.client = types.SimpleNamespace(host=ip)
        self.headers = headers or {}
        self.cookies = cookies or {}


class Response:
    def __init__(self, content=None, media_type=None, headers=None):
        self.body = content
        self.media_type = media_type
        self.headers = headers or {}
        self.cookies = {}

    def set_cookie(self, k, v, **kw):
        self.cookies[k] = v

    def delete_cookie(self, k, **kw):
        self.cookies.pop(k, None)


class UploadFile:
    def __init__(self, filename, content_type, data):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self, size=-1):
        return self._data if size is None or size < 0 else self._data[:size]


ROUTES = []


class APIRouter:
    def __init__(self, prefix=""):
        self.prefix = prefix

    def _reg(self, method, path):
        def deco(fn):
            ROUTES.append((method, self.prefix + path, fn.__name__))
            return fn
        return deco

    def get(self, path, **kw):
        return self._reg("GET", path)

    def post(self, path, **kw):
        return self._reg("POST", path)

    def patch(self, path, **kw):
        return self._reg("PATCH", path)

    def delete(self, path, **kw):
        return self._reg("DELETE", path)


class FastAPI:
    def __init__(self, **kw):
        self.lifespan = kw.get("lifespan")

    def on_event(self, name):
        return lambda fn: fn

    def include_router(self, r):
        pass

    def add_middleware(self, *a, **kw):
        pass


fastapi = types.ModuleType("fastapi")
for name, obj in dict(FastAPI=FastAPI, APIRouter=APIRouter, HTTPException=HTTPException, Request=Request,
                      Response=Response, UploadFile=UploadFile,
                      Depends=lambda x=None: None, Query=lambda d=None, **kw: d, File=lambda d=None, **kw: d).items():
    setattr(fastapi, name, obj)
sys.modules["fastapi"] = fastapi


# ---------------- bcrypt ----------------
bcrypt = types.ModuleType("bcrypt")
bcrypt.gensalt = lambda: b""
def _bcrypt5_limit(pw):  # como bcrypt 5: error si la contraseña supera 72 bytes
    if len(pw) > 72:
        raise ValueError("password cannot be longer than 72 bytes")
    return pw


bcrypt.hashpw = lambda pw, salt: b"h:" + _bcrypt5_limit(pw)
bcrypt.checkpw = lambda pw, hashed: hashed == b"h:" + _bcrypt5_limit(pw)
sys.modules["bcrypt"] = bcrypt


# ---------------- segno ----------------
segno = types.ModuleType("segno")


class _QR:
    def __init__(self, data, error=None):
        self.data = data

    def save(self, out, kind=None, scale=1, border=4, dark="#000"):
        assert kind == "png"
        out.write(b"\x89PNG-fake-" + self.data.encode())


segno.make = lambda data, error=None: _QR(data, error)
sys.modules["segno"] = segno
