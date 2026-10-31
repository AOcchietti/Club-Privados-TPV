"""Prueba de punta a punta contra un servidor REAL (FastAPI + MongoDB de verdad), por HTTP como el navegador.

Las otras pruebas llaman a las funciones del backend con una base de datos en memoria. Esta comprueba lo que
solo se ve con el servidor de verdad: cookies, cabecera CSRF, subidas multipart, índices únicos de MongoDB,
fechas que devuelve MongoDB, ventas simultáneas, PDF y que todo sigue ahí tras reiniciar.

ESCRIBE DATOS (productos, ventas, turnos…): úsala con una base de datos de pruebas, nunca con la del club.

    python tests/e2e_real.py http://localhost:8001 --si            # fase 1: todo el recorrido
    python tests/e2e_real.py http://localhost:8001 --si --fase 2   # fase 2: después de reiniciar el servidor

Credenciales del admin: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD (por defecto las de ejemplo).
"""
import concurrent.futures as cf
import json
import os
import sys
import tempfile
import time
import uuid

import requests

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
STATE = os.path.join(tempfile.gettempdir(), "tpv-e2e-estado.json")
GHA = os.environ.get("GITHUB_ACTIONS") == "true"


class Fallo(Exception):
    pass


class Cliente:
    """Cliente HTTP mínimo que guarda las cookies a mano (también las Secure sobre http://localhost)."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookies = {}

    def req(self, method, path, csrf=True, cookies=None, **kw):
        headers = dict(kw.pop("headers", {}))
        if csrf:
            headers["X-Requested-With"] = "XMLHttpRequest"
        jar = self.cookies if cookies is None else cookies
        if jar:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
        r = requests.request(method, self.base + path, headers=headers, timeout=30, **kw)
        for c in r.cookies:
            if c.value:
                self.cookies[c.name] = c.value
            else:
                self.cookies.pop(c.name, None)
        if r.status_code >= 500:
            raise Fallo(f"{method} {path} → error interno {r.status_code}: {r.text[:200]}")
        return r

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, **kw):
        return self.req("POST", path, **kw)

    def ok(self, method, path, **kw):
        r = self.req(method, path, **kw)
        if r.status_code != 200:
            raise Fallo(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if "json" in r.headers.get("content-type", "") else r


checks = 0


def check(cond, msg):
    global checks
    if not cond:
        raise Fallo(msg)
    checks += 1
    print(f"  ✔ {msg}")


def login(base):
    c = Cliente(base)
    email = os.environ.get("E2E_ADMIN_EMAIL", "admin@weedlemon.es")
    pw = os.environ.get("E2E_ADMIN_PASSWORD", "admin123")
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        raise Fallo(f"login del admin → {r.status_code}: {r.text[:200]}")
    return c, r


def fase1(base):
    c0 = Cliente(base)
    print("Servidor y cabeceras")
    r = c0.get("/api/")
    check(r.status_code == 200 and "API" in r.json().get("message", ""), "la API responde")
    check(r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("x-frame-options") == "DENY", "cabeceras de seguridad")
    r = c0.post("/api/auth/login", csrf=False, json={"email": "admin@weedlemon.es", "password": "x"})
    check(r.status_code == 403 and "CSRF" in r.text, "sin la cabecera CSRF se rechaza cualquier escritura")

    print("Login y bloqueo por intentos (fallo n.º 1 de la auditoría: solo se ve con MongoDB real)")
    intruso = f"nadie-{uuid.uuid4().hex[:6]}@e2e.test"
    codes = [c0.post("/api/auth/login", json={"email": intruso, "password": "mala"}).status_code for _ in range(7)]
    check(codes[:5] == [401] * 5 and set(codes[5:]) == {429}, f"5 fallos → bloqueo 429, nunca error interno ({codes})")
    c, r = login(base)
    check("token" not in r.json() and "password_hash" not in r.json(), "el login no devuelve token ni hash")
    sc = r.headers.get("set-cookie", "").lower()
    check("access_token=" in sc and "httponly" in sc, "la sesión viaja en cookie httpOnly")
    check(c.get("/api/auth/me").json()["role"] == "admin", "sesión de administrador")

    print("Cierre de sesión en el servidor (antes un token copiado valía 8 h)")
    c2, _ = login(base)
    robada = dict(c2.cookies)
    c2.ok("POST", "/api/auth/logout")
    check(c2.get("/api/auth/me", cookies=robada).status_code == 401, "la cookie copiada deja de valer al cerrar sesión")
    check(c2.post("/api/auth/refresh", cookies=robada).status_code == 401, "y tampoco sirve para renovar la sesión")

    cur = c.ok("GET", "/api/cash/current")
    if cur.get("session"):
        raise Fallo("Hay un turno activo en esta base de datos: usa una base de datos de pruebas vacía")

    print("Categorías y subcategorías")
    tag = uuid.uuid4().hex[:5]
    madre = c.ok("POST", "/api/categories", json={"label": f"E2E Flores {tag}", "color": "lime"})
    sub = c.ok("POST", "/api/categories", json={"label": "Índica", "color": "purple", "parent": madre["key"]})
    check(sub["parent"] == madre["key"], "subcategoría creada dentro de su madre")
    cats = [x["key"] for x in c.ok("GET", "/api/categories")]
    check(cats.index(sub["key"]) == cats.index(madre["key"]) + 1, "la subcategoría sale justo después de su madre")
    p_sub = c.ok("POST", "/api/products", json={"name": f"E2E Gelato {tag}", "category": sub["key"], "price": 10, "unit": "g", "initial_stock": 20})
    en_madre = c.ok("GET", "/api/products", params={"category": madre["key"], "active_only": "true"})
    check([p["id"] for p in en_madre] == [p_sub["id"]], "filtrar por la madre incluye las subcategorías (operador $in real)")

    print("Subidas de archivos (multipart real)")
    up = c.ok("POST", "/api/upload", files={"file": ("foto.png", PNG, "image/png")})
    got = c.get(f"/api/files/{up['path']}")
    check(got.status_code == 200 and got.content == PNG, "la foto se sube y se descarga intacta")
    bad = c.post("/api/upload", files={"file": ("x.png", SVG, "image/png")})
    check(bad.status_code == 400, "un SVG con script disfrazado de PNG se rechaza")

    print("Venta y recarga fuera de turno")
    socios = [u for u in c.ok("GET", "/api/users", params={"role": "socio"}) if u.get("status") == "activa"]
    socio = socios[0]
    v = c.ok("POST", "/api/sales", json={"items": [{"product_id": p_sub["id"], "qty": 2}], "socio_id": socio["id"]})
    check(v["out_of_shift"] and v["total"] == 20, "venta fuera de turno")
    rc = c.ok("POST", f"/api/users/{socio['id']}/recharge", json={"amount": 20})
    check(rc.get("recharge_out_of_shift"), "recarga fuera de turno")

    print("Apertura: dos dispositivos a la vez (índice único de MongoDB)")
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda _: c.post("/api/cash/open", json={"starting_amount": 100}).status_code, range(6)))
    check(res.count(200) == 1 and all(code == 400 for code in res if code != 200), f"solo se abre un turno ({res})")
    st = c.ok("GET", "/api/cash/current")["stocktake"]
    check(st["kind"] == "opening" and madre["label"] in st["sections"], "recuento de apertura con la categoría madre como sección")
    line = next(l for l in st["lines"] if l["product_id"] == p_sub["id"])
    check(line["expected"] == 18 and line["subcategory_label"] == "Índica", "la venta fuera de turno se descuenta al abrir")
    st = c.ok("POST", "/api/cash/stocktake/autofill", json={"all": True, "version": st["version"]})
    check(all(l["counted"] == l["expected"] for l in st["lines"]), "botón de rellenar todo el recuento")
    c.ok("POST", "/api/cash/opening/confirm")

    print("Ventas simultáneas en turno (atomicidad real)")
    lata = c.ok("POST", "/api/products", json={"name": f"E2E Lata {tag}", "category": "refrescos", "price": 2, "unit": "ud", "initial_stock": 5})
    with cf.ThreadPoolExecutor(12) as ex:
        codes = list(ex.map(lambda _: c.post("/api/sales", json={"items": [{"product_id": lata["id"], "qty": 1}], "socio_id": socio["id"]}).status_code, range(12)))
    stock = next(p for p in c.ok("GET", "/api/products") if p["id"] == lata["id"])["stock"]
    check(codes.count(200) == 5 and stock == 0, f"12 ventas a la vez de 5 latas: se venden 5 y el stock queda en 0 ({codes.count(200)} ventas, stock {stock})")
    choco = c.ok("POST", "/api/products", json={"name": f"E2E Choco {tag}", "category": "dulces", "price": 1.5, "unit": "ud", "initial_stock": 3})
    media = c.post("/api/sales", json={"items": [{"product_id": choco["id"], "qty": 0.5}], "socio_id": socio["id"]})
    check(media.status_code == 400 and "entero" in media.json().get("detail", ""), "no se vende media chocolatina")

    print("Cierre y PDF")
    c.ok("POST", "/api/cash/closing/start")
    c.ok("POST", "/api/cash/closing/cash", json={"counted": 120, "reason": "prueba e2e"})
    st = c.ok("POST", "/api/cash/closing/stocktake/start")
    st = c.ok("POST", "/api/cash/stocktake/autofill", json={"all": True, "version": st["version"]})
    closed = c.ok("POST", "/api/cash/closing/finalize")
    check(closed["status"] == "closed", "turno cerrado")
    pdf = c.get(f"/api/cash/sessions/{closed['id']}/report.pdf")
    check(pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and b"/Count 1" in pdf.content, "PDF del cierre en una página")

    print("Alta pública")
    pub = Cliente(base)
    fotos = [pub.ok("POST", "/api/public/upload", files={"file": (f"{k}.png", PNG, "image/png")})["path"] for k in ("doc", "cara", "firma")]
    alta = pub.ok("POST", "/api/public/alta", json={
        "name": "E2E", "apellidos": "Prueba", "doc_type": "DNI", "doc_number": f"{uuid.uuid4().int % 10**8:08d}Z",
        "nationality": "Española", "birthdate": "1990-01-01", "phone": "600000000", "doc_photo": fotos[0],
        "face_photo": fotos[1], "signature": fotos[2], "legal_accepted": True})
    check(set(alta) == {"name", "member_number"}, "el formulario público solo devuelve nombre y nº de socio")
    check(pub.get(f"/api/files/{fotos[0]}").status_code == 401, "las fotos del DNI no se pueden ver sin sesión")

    productos = c.ok("GET", "/api/products")
    json.dump({"foto": up["path"], "madre": madre["key"], "sub": sub["key"], "productos": len(productos)}, open(STATE, "w"))


def fase2(base):
    estado = json.load(open(STATE))
    print("Después de reiniciar el servidor")
    c, _ = login(base)
    check(True, "el admin sigue entrando (su contraseña no se reescribe al arrancar)")
    productos = c.ok("GET", "/api/products")
    check(len(productos) == estado["productos"], "no se duplican ni reaparecen productos al reiniciar")
    check(sum(p["name"] == "Coca-Cola" for p in productos) == 1, "los refrescos de ejemplo solo se crean una vez")
    got = c.get(f"/api/files/{estado['foto']}")
    check(got.status_code == 200 and got.content == PNG, "las fotos siguen ahí tras reiniciar")
    keys = [x["key"] for x in c.ok("GET", "/api/categories")]
    check(estado["sub"] in keys and estado["madre"] in keys, "categorías y subcategorías intactas")


def main():
    args = sys.argv[1:]
    if not args or "--si" not in args:
        print(__doc__)
        sys.exit(2)
    base = args[0]
    fase = args[args.index("--fase") + 1] if "--fase" in args else "1"
    t0 = time.time()
    try:
        (fase2 if fase == "2" else fase1)(base)
    except (Fallo, AssertionError, requests.RequestException) as e:
        print(f"\n✘ FALLO: {e}")
        if GHA:
            print(f"::error title=Servidor real (fase {fase})::{e}")
        sys.exit(1)
    msg = f"{checks} comprobaciones correctas contra el servidor real en {time.time() - t0:.1f} s"
    print(f"\nOK · {msg}")
    if GHA:
        print(f"::notice title=Servidor real (fase {fase})::{msg}")


if __name__ == "__main__":
    main()
