"""Pruebas de seguridad, organizadas según la tríada CIA.

C · Confidencialidad: solo quien debe puede entrar y ver datos (sesiones, roles, accesos).
I · Integridad: nadie puede alterar datos de forma indebida (CSRF, inyección, asignación masiva,
    subidas maliciosas, reglas de negocio).
A · Disponibilidad: el servicio aguanta abusos (fuerza bruta, subidas enormes, búsquedas trampa).
"""
import ast
import asyncio
import os
import re
import time

import jwt
from pydantic import ValidationError

from common import S, Checker, as_user, PNG, JPG, BACKEND

CHK = Checker("seguridad")
check = CHK
err = CHK.error

PUBLIC = {("POST", "/auth/login"), ("POST", "/auth/refresh"), ("POST", "/auth/logout"), ("POST", "/auth/forgot-password"), ("POST", "/auth/reset-password"), ("POST", "/public/upload"), ("POST", "/public/alta"),
          ("GET", "/public/legal"), ("GET", "/public/legal.pdf"), ("GET", "/alta/qr.png"), ("GET", "/")}
ADMIN_ONLY = {("DELETE", "/users/{user_id}"), ("POST", "/settings/legal-pdf"), ("POST", "/cash/opening/cancel"),
              ("POST", "/cash/closing/cancel"), ("GET", "/cash/sessions"), ("GET", "/cash/sessions/{session_id}"),
              ("GET", "/dashboard/stats"), ("GET", "/activity")}
SESSION_ONLY = {("POST", "/auth/logout"), ("GET", "/auth/me"), ("GET", "/files/{path:path}")}


def route_matrix():
    """Lee server.py y devuelve {(método, ruta): dependencia de acceso}."""
    tree = ast.parse(open(os.path.join(BACKEND, "server.py"), encoding="utf-8").read())
    out = {}
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "api_router":
                deps = [ast.unparse(x.args[0]) for x in node.args.defaults
                        if isinstance(x, ast.Call) and getattr(x.func, "id", "") == "Depends" and x.args]
                out[(d.func.attr.upper(), d.args[0].value)] = deps[0] if deps else None
    return out


def token(sub, kind="access", minutes=30, secret=None, **extra):
    payload = {"sub": sub, "type": kind, "exp": int(time.time()) + minutes * 60, **extra}
    return jwt.encode(payload, secret or os.environ["JWT_SECRET"], algorithm="HS256")


async def asgi_call(_unused, method, path, headers=None):
    """Pasa una petición por SecurityMiddleware y devuelve (estado, cabeceras, ¿llegó a la API?)."""
    reached = {"v": False}

    async def inner(scope, receive, send):
        reached["v"] = True
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": method, "path": path,
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}
    await S.SecurityMiddleware(inner)(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], dict(start["headers"]), reached["v"]


async def main():
    db = S.db
    await S.startup()
    admin = await as_user("admin@weedlemon.es")
    cajero = await as_user("cajero@weedlemon.es")
    socio = await db.users.find_one({"role": "socio"})

    # ================= C · CONFIDENCIALIDAD =================
    # Mapa de accesos: cada ruta tiene la protección esperada (análisis del código)
    matrix = route_matrix()
    check(len(matrix) >= 45, "se han encontrado todas las rutas de la API")
    for route, dep in matrix.items():
        if route in PUBLIC:
            check(dep is None, f"{route} es pública a propósito")
        elif route in ADMIN_ONLY:
            check(dep == "require_admin", f"{route} exige administrador (tiene {dep})")
        elif route in SESSION_ONLY:
            check(dep == "get_current_user", f"{route} exige sesión (tiene {dep})")
        else:
            check(dep == "require_staff", f"{route} exige ser del equipo (tiene {dep})")

    # Comprobación de roles
    await err(S.require_admin(user=cajero), 403)
    check((await S.require_admin(user=admin))["role"] == "admin", "admin pasa el control de administrador")
    await err(S.require_staff(user={**cajero, "role": "socio"}), 403)

    # Sesiones (JWT)
    def req(tok=None, bearer=None):
        return S.Request(cookies={"access_token": tok} if tok else {},
                         headers={"Authorization": f"Bearer {bearer}"} if bearer else {})
    await err(S.get_current_user(req()), 401, "no autenticado")
    ok = await S.get_current_user(req(token(cajero["id"])))
    check(ok["email"] == "cajero@weedlemon.es", "token válido aceptado")
    yo = await S.me(user=ok)  # lo que pide la app al recargar la página
    check(yo["id"] == cajero["id"] and "password_hash" not in yo and "_id" not in yo, "/auth/me responde con la sesión actual (antes daba error 500)")
    check((await S.get_current_user(req(bearer=token(cajero["id"]))))["id"] == cajero["id"], "token por cabecera Bearer")
    await err(S.get_current_user(req(token(cajero["id"], minutes=-1))), 401, "expirada")
    await err(S.get_current_user(req(token(cajero["id"], secret="otra-clave-que-no-es-la-buena-0000000"))), 401, "inválido")
    await err(S.get_current_user(req(token(cajero["id"], kind="refresh"))), 401, "inválido")
    none_alg = jwt.encode({"sub": admin["id"], "type": "access", "exp": int(time.time()) + 600}, key=None, algorithm="none")
    await err(S.get_current_user(req(none_alg)), 401, "inválido")
    await err(S.get_current_user(req(token("no-es-un-id"))), 401)
    await err(S.get_current_user(req(token("0" * 24))), 401, "no encontrado")
    await err(S.get_current_user(req(token(str(socio["_id"])))), 401, "sin acceso")
    forged = token(cajero["id"], role="admin")  # el rol del token no cuenta: se lee de la base de datos
    me = await S.get_current_user(req(forged))
    await err(S.require_admin(user=me), 403)
    pepe = await S.create_user(S.UserCreate(name="Pepe", role="cajero", email="pepe@x.es", password="pepe-clave-1"), user=admin)
    tok_pepe = token(pepe["id"])
    await S.update_user(pepe["id"], S.UserUpdate(status="suspendida"), user=admin)
    await err(S.get_current_user(req(tok_pepe)), 401, "sin acceso")
    refresh_req = S.Request(cookies={"refresh_token": token(pepe["id"], kind="refresh")})
    await err(S.refresh(refresh_req, S.Response()), 401, "sin acceso")

    # El login no devuelve el token en el cuerpo y las cookies son httpOnly
    res = S.Response()
    out = await S.login(S.LoginIn(email="admin@weedlemon.es", password="admin123"), S.Request(), res)
    check("token" not in out and "password_hash" not in out, "login sin token ni hash en la respuesta")
    await err(S.login(S.LoginIn(email="pepe@x.es", password="pepe-clave-1"), S.Request(ip="7.7.7.7"), S.Response()), 403, "suspendida")
    check(all("password_hash" not in u for u in await S.list_users(role=None, q=None, user=admin)), "nunca se devuelve el hash de contraseñas")

    # Cerrar sesión anula los tokens en el servidor: una copia robada de la cookie deja de servir
    res = S.Response()
    await S.login(S.LoginIn(email="cajero@weedlemon.es", password="cajero123"), S.Request(ip="8.8.4.4"), res)
    acc, ref = res.cookies["access_token"], res.cookies["refresh_token"]
    check((await S.get_current_user(req(acc)))["email"] == "cajero@weedlemon.es", "sesión válida antes de salir")
    out_res = S.Response()
    out_res.cookies = {"access_token": "x", "refresh_token": "y"}
    await S.logout(S.Request(cookies={"access_token": acc, "refresh_token": ref}), out_res)
    check(out_res.cookies == {}, "el cierre de sesión borra las cookies")
    await err(S.get_current_user(req(acc)), 401, "sesión cerrada")
    await err(S.get_current_user(req(bearer=acc)), 401, "sesión cerrada")
    await err(S.refresh(S.Request(cookies={"refresh_token": ref}), S.Response()), 401, "sesión cerrada")
    check(await db.revoked_tokens.count_documents({}) == 2, "los dos tokens quedan anulados hasta que caducan")
    await S.logout(S.Request(cookies={"access_token": "basura", "refresh_token": token(cajero["id"], minutes=-5)}), S.Response())
    check(True, "cerrar sesión con tokens caducados o rotos no da error")
    res = S.Response()
    await S.login(S.LoginIn(email="cajero@weedlemon.es", password="cajero123"), S.Request(ip="8.8.4.4"), res)
    check((await S.get_current_user(req(res.cookies["access_token"])))["email"] == "cajero@weedlemon.es", "volver a entrar funciona")

    # Recuperación de contraseña por email
    enviados = []

    async def fake_send(to, subject, text, html=None):
        enviados.append({"to": to, "subject": subject, "text": text, "html": html})
        return True
    real_send = S.send_email
    S.send_email = fake_send
    try:
        async def pedir(email, ip="5.5.5.5", headers=None):
            out = await S.forgot_password(S.ForgotPasswordIn(email=email), S.Request(ip=ip, headers=headers or {}))
            await asyncio.gather(*list(S.BACKGROUND_TASKS))
            return out
        r_nadie = await pedir("nadie@weedlemon.es")
        r_socio = await pedir("lucia@example.com")
        check(not enviados, "a un email que no es del equipo no se le envía nada")
        res_login = S.Response()
        await S.login(S.LoginIn(email="cajero@weedlemon.es", password="cajero123"), S.Request(ip="5.5.5.6"), res_login)
        sesion_vieja = res_login.cookies["access_token"]
        r_cajero = await pedir(" Cajero@WeedLemon.es ", headers={"host": "web-del-atacante.example"})
        check(r_nadie == r_socio == r_cajero, "la respuesta es idéntica exista o no la cuenta (no revela emails)")
        check(len(enviados) == 1 and enviados[0]["to"] == "cajero@weedlemon.es", "se envía el enlace al email de la cuenta")
        link = re.search(r"(https?://\S+/restablecer\?token=)([\w-]+)", enviados[0]["text"])
        check(link and link.group(1).startswith(S.public_app_url()), "el enlace usa la dirección configurada, nunca la cabecera Host")
        tok = link.group(2)
        check(tok in (enviados[0]["html"] or ""), "el correo HTML lleva el mismo enlace")
        rec = await db.password_resets.find_one({"used_at": None})
        check(rec["token_hash"] != tok and len(tok) >= 40, "solo se guarda el hash del token, que es largo y aleatorio")
        await err(S.reset_password(S.ResetPasswordIn(token=tok, password="corta"), S.Request(ip="5.5.5.7")), 400, "8 caracteres")
        await err(S.reset_password(S.ResetPasswordIn(token="inventado", password="nueva-clave-123"), S.Request(ip="5.5.5.7")), 400, "no es válido")
        await S.reset_password(S.ResetPasswordIn(token=tok, password="nueva-clave-123"), S.Request(ip="5.5.5.7"))
        await asyncio.gather(*list(S.BACKGROUND_TASKS))
        check(any("se ha cambiado" in m["subject"] for m in enviados), "se avisa por correo del cambio")
        await err(S.reset_password(S.ResetPasswordIn(token=tok, password="otra-clave-456"), S.Request(ip="5.5.5.7")), 400, "no es válido")
        check(True, "el enlace solo sirve una vez")
        await err(S.get_current_user(req(sesion_vieja)), 401, "contraseña ha cambiado")
        await err(S.login(S.LoginIn(email="cajero@weedlemon.es", password="cajero123"), S.Request(ip="5.5.5.8"), S.Response()), 401)
        ok_res = S.Response()
        await S.login(S.LoginIn(email="cajero@weedlemon.es", password="nueva-clave-123"), S.Request(ip="5.5.5.8"), ok_res)
        check((await S.get_current_user(req(ok_res.cookies["access_token"])))["email"] == "cajero@weedlemon.es", "se entra con la contraseña nueva")
        # Caducidad, enlaces anteriores y límite de correos
        enviados.clear()
        await pedir("cajero@weedlemon.es", ip="5.5.6.1")
        tok1 = re.search(r"token=([\w-]+)", enviados[-1]["text"]).group(1)
        await pedir("cajero@weedlemon.es", ip="5.5.6.2")
        tok2 = re.search(r"token=([\w-]+)", enviados[-1]["text"]).group(1)
        await err(S.reset_password(S.ResetPasswordIn(token=tok1, password="clave-larga-789"), S.Request(ip="5.5.6.3")), 400, "no es válido")
        check(True, "pedir un enlace nuevo anula el anterior")
        await db.password_resets.update_one({"token_hash": S.reset_token_hash(tok2)}, {"$set": {"expires_at": S.now_utc() - S.timedelta(minutes=1)}})
        await err(S.reset_password(S.ResetPasswordIn(token=tok2, password="clave-larga-789"), S.Request(ip="5.5.6.3")), 400, "caducado")
        check(True, "un enlace caducado no sirve")
        antes = len(enviados)
        for i in range(3):
            await pedir("cajero@weedlemon.es", ip=f"5.5.7.{i}")
        check(len(enviados) == antes, f"como mucho {S.RESET_MAX_PER_HOUR} correos por hora a la misma cuenta")
        for i in range(10):
            await pedir(f"x{i}@weedlemon.es", ip="5.5.9.9")
        await err(pedir("x@weedlemon.es", ip="5.5.9.9"), 429)
        check(True, "límite de peticiones por conexión")
        await S.update_user(pepe["id"], S.UserUpdate(status="suspendida"), user=admin)
        antes = len(enviados)
        await pedir("pepe@x.es", ip="5.5.8.1")
        check(len(enviados) == antes, "una cuenta suspendida no recibe enlaces")
        # Un admin que cambia la contraseña de otra persona cierra sus sesiones
        res_c = S.Response()
        await S.login(S.LoginIn(email="cajero@weedlemon.es", password="nueva-clave-123"), S.Request(ip="5.5.8.2"), res_c)
        await S.update_user(cajero["id"], S.UserUpdate(password="cajero123"), user=admin)
        await err(S.get_current_user(req(res_c.cookies["access_token"])), 401, "contraseña ha cambiado")
        await err(S.refresh(S.Request(cookies={"refresh_token": res_c.cookies["refresh_token"]}), S.Response()), 401, "contraseña ha cambiado")
        check(True, "si un admin cambia la contraseña de alguien, sus sesiones abiertas caducan")
    finally:
        S.send_email = real_send

    # Envío real del correo: proveedor según la configuración
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            sent.update(host=host, port=port)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self, context=None):
            sent["tls"] = True
        def login(self, u, p):
            sent["login"] = u
        def send_message(self, msg):
            sent["msg"] = msg
    real_smtp, real_post = S.smtplib.SMTP, S.requests.post
    S.smtplib.SMTP = FakeSMTP
    os.environ.update(SMTP_HOST="smtp.ejemplo.es", SMTP_USER="tpv@ejemplo.es", SMTP_PASSWORD="x", EMAIL_FROM="tpv@ejemplo.es")
    try:
        check(S.email_provider() == "smtp" and await S.send_email("a@b.es", "Prueba", "hola", "<p>hola</p>"), "envío por SMTP")
        check(sent["port"] == 587 and sent.get("tls") and sent["login"] == "tpv@ejemplo.es" and sent["msg"]["To"] == "a@b.es",
              "SMTP con STARTTLS, usuario y destinatario correctos")
        llamadas = []
        S.requests.post = lambda url, **kw: (llamadas.append((url, kw)), type("R", (), {"status_code": 201, "text": ""})())[1]
        os.environ["BREVO_API_KEY"] = "clave-brevo"
        check(S.email_provider() == "brevo" and await S.send_email("a@b.es", "Prueba", "hola"), "envío por la API de Brevo")
        url, kw = llamadas[0]
        check(url.startswith("https://api.brevo.com/") and kw["headers"]["api-key"] == "clave-brevo" and kw["json"]["to"] == [{"email": "a@b.es"}],
              "Brevo por HTTPS (sirve aunque el hosting bloquee SMTP)")
        S.requests.post = lambda url, **kw: type("R", (), {"status_code": 401, "text": "bad key"})()
        check(await S.send_email("a@b.es", "Prueba", "hola") is False, "si el proveedor falla, la petición no se rompe")
    finally:
        S.smtplib.SMTP, S.requests.post = real_smtp, real_post
        for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM", "BREVO_API_KEY"):
            os.environ.pop(k, None)

    # bcrypt 5 da error con contraseñas de más de 72 bytes: se rechazan al crearlas y el login nunca falla por ello
    await err(S.create_user(S.UserCreate(name="Larga", role="cajero", email="larga@x.es", password="ñ" * 40), user=admin), 400, "72")
    await err(S.login(S.LoginIn(email="cajero@weedlemon.es", password="x" * 500), S.Request(ip="8.8.8.4"), S.Response()), 401)
    try:
        same72 = S.verify_password("a" * 72 + "resto", S.hash_password("a" * 72 + "otra"))
    except ValueError:  # lo que haría bcrypt 5 sin el recorte
        same72 = False
    check(same72, "se usan los primeros 72 bytes, como con bcrypt 4 (y bcrypt 5 no da error)")

    # Producción con JWT_SECRET corto: el servidor no arranca
    real_secret, real_secure = os.environ["JWT_SECRET"], S.COOKIE_SECURE
    os.environ["JWT_SECRET"], S.COOKIE_SECURE = "corta", True
    try:
        await S.startup()
        check(False, "no debería arrancar con una clave corta en producción")
    except RuntimeError as e:
        check("JWT_SECRET" in str(e), "en producción no arranca con JWT_SECRET corto")
    finally:
        os.environ["JWT_SECRET"], S.COOKIE_SECURE = real_secret, real_secure

    # Datos personales: el cajero no ve al equipo ni el histórico completo; el PDF solo para responsable/admin
    check(all(u["role"] == "socio" for u in await S.list_users(role="admin", q=None, user=cajero)), "el cajero no puede listar al equipo")
    await err(S.list_sales(range="all", payment=None, socio_id=None, user=cajero), 403)
    await err(S.update_user(admin["id"], S.UserUpdate(name="hackeado"), user=cajero), 403)

    # Alta pública: no filtra datos internos
    up = await S.public_upload(S.Request(), S.UploadFile("f.png", "image/png", PNG))
    alta = await S.public_alta(S.PublicAltaIn(name="Eva", apellidos="Sol", doc_type="DNI", doc_number="99999999R", nationality="ES",
                                              birthdate="1990-01-01", phone="600", doc_photo=up["path"], face_photo=up["path"],
                                              signature=up["path"], legal_accepted=True), S.Request())
    check(set(alta) == {"name", "member_number"}, "el formulario público solo devuelve nombre y nº de socio")

    # Cabeceras de seguridad y CORS
    status, headers, _ = await asgi_call(S.SecurityMiddleware(None), "GET", "/api/products")
    check(headers.get(b"x-content-type-options") == b"nosniff" and headers.get(b"x-frame-options") == b"DENY", "cabeceras nosniff y anti-iframe")
    check(headers.get(b"referrer-policy") == b"no-referrer", "cabecera referrer-policy")
    saved = S.COOKIE_SECURE
    S.COOKIE_SECURE = True
    os.environ["FRONTEND_URL"] = "https://club.example"
    check(S.allowed_origins() == ["https://club.example"], "en producción CORS solo admite el dominio del frontend")
    S.COOKIE_SECURE = saved

    # ================= I · INTEGRIDAD =================
    # CSRF: sin la cabecera X-Requested-With, ninguna petición que modifique datos llega a la API
    mw = S.SecurityMiddleware(None)
    for method in ("POST", "PATCH", "DELETE"):
        status, _, reached = await asgi_call(mw, method, "/api/sales")
        check(status == 403 and not reached, f"CSRF: {method} sin cabecera rechazado")
    status, _, reached = await asgi_call(mw, "POST", "/api/sales", {"X-Requested-With": "XMLHttpRequest"})
    check(status == 200 and reached, "CSRF: con la cabecera del frontend pasa")
    status, _, reached = await asgi_call(mw, "POST", "/api/public/alta")
    check(status == 403 and not reached, "CSRF también en el formulario público")
    for method in ("GET", "OPTIONS"):
        status, _, reached = await asgi_call(mw, method, "/api/products")
        check(reached, f"{method} no necesita la cabecera (no modifica datos)")

    # Subidas: solo imágenes reales; nada de SVG/HTML disfrazados
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.cookie)"></svg>'
    await err(S.upload(S.UploadFile("x.svg", "image/svg+xml", svg), user=cajero), 400, "JPG, PNG")
    await err(S.upload(S.UploadFile("x.png", "image/png", b"<html><script>alert(1)</script>"), user=cajero), 400)
    await err(S.public_upload(S.Request(ip="5.5.5.5"), S.UploadFile("x.gif", "image/gif", b"GIF8 falso")), 400)
    for name, data, ctype in [("a.png", PNG, "image/png"), ("a.jpg", JPG, "image/jpeg"), ("a.gif", b"GIF89a" + b"\0" * 20, "image/gif"),
                              ("a.webp", b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 20, "image/webp")]:
        path = (await S.upload(S.UploadFile(name, "application/octet-stream", data), user=cajero))["path"]
        rec = await db.files.find_one({"storage_path": path})
        check(rec["content_type"] == ctype, f"{name}: tipo detectado por contenido ({ctype}), no por lo que dice el navegador")
    await err(S.upload_legal_pdf(S.UploadFile("a.pdf", "application/pdf", b"<html>no soy pdf</html>"), user=admin), 400, "pdf")
    # Archivos antiguos de tipo peligroso se sirven como descarga, nunca como página
    await db.files.insert_one({"storage_path": "weedlemon/viejo.html", "content_type": "text/html", "is_deleted": False})
    await S.put_object("weedlemon/viejo.html", b"<script>alert(1)</script>", "text/html")
    resp = await S.download_file("weedlemon/viejo.html", user=cajero)
    check(resp.media_type == "application/octet-stream", "HTML antiguo se sirve como descarga")
    resp = await S.download_file(path, user=cajero)
    check("default-src 'none'" in resp.headers.get("Content-Security-Policy", ""), "las imágenes se sirven con CSP restrictiva")
    await err(S.get_object("../../etc/passwd"), 400, "ruta")
    await err(S.download_file("weedlemon/no-registrado.png", user=cajero), 404)

    # Inyección: búsquedas tratadas como texto, tipos estrictos, ids validados
    check(await S.list_products(q=".*", category=None, active_only=False, user=cajero) == [], "'.*' se busca como texto, no como patrón")
    check(await S.list_users(role=None, q="^", user=admin) == [], "'^' se busca como texto")
    for bad in [{"$gt": ""}, ["admin"], {"$ne": None}]:
        try:
            S.LoginIn(email=bad, password="x")
            check(False, f"LoginIn aceptó {bad}")
        except ValidationError:
            check(True, "operadores de MongoDB rechazados por tipo")
    await err(S.get_user('{"$gt": ""}', user=admin), 404)
    xss = '<img src=x onerror=alert(1)> ( \\ )'
    p = await S.create_product(S.ProductCreate(name=xss, category="sativa", price=1, initial_stock=0), user=cajero)
    check(p["name"] == xss, "el texto se guarda tal cual (React lo escapa al mostrarlo)")
    from cierre_pdf import _escape
    check(_escape("a(b)c\\") == "a\\(b\\)c\\\\", "el PDF escapa paréntesis y barras (no se puede inyectar código PDF)")

    # Asignación masiva: campos que no se pueden tocar desde la API
    s_id = str(socio["_id"])
    before = await db.users.find_one({"_id": socio["_id"]})
    sneaky = S.UserUpdate(name="Nuevo nombre", role="admin", status="activa")
    sneaky_dict = sneaky.model_dump()
    sneaky_dict.update({"balance": 99999, "member_number": "WL-9999", "password_hash": "x"})
    await S.update_user(s_id, S.UserUpdate(**{k: v for k, v in sneaky_dict.items() if k in S.UserUpdate.model_fields}), user=cajero)
    after = await db.users.find_one({"_id": socio["_id"]})
    check(after["role"] == "socio" and after["balance"] == before["balance"] and after["member_number"] == before["member_number"],
          "el cajero no puede cambiar rol, saldo ni nº de socio")

    # Reglas de negocio contra manipulación
    lemon = await db.products.find_one({"name": "Lemon Haze"})
    lid = str(lemon["_id"])
    await err(S.recharge_balance(s_id, S.RechargeIn(amount=-50), user=cajero), 400)
    await err(S.recharge_balance(s_id, S.RechargeIn(amount=1000.01), user=cajero), 400)
    await err(S.recharge_balance(s_id, S.RechargeIn(amount=10, method="tarjeta"), user=cajero), 400)
    await err(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=lid, qty=-2)], socio_id=s_id), user=cajero), 400)
    await err(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=lid, qty=10**9)], socio_id=s_id), user=cajero), 400)
    await err(S.create_product(S.ProductCreate(name="x", category="sativa", price=-5), user=cajero), 400)
    await err(S.stock_movement(lid, S.StockMoveIn(type="ajuste", qty=10**9, reason="x"), user=cajero), 400, "rango")
    sale = await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=lid, qty=1)], socio_id=s_id, payment_method="regalo"), user=cajero)
    check(sale["total"] == lemon["price"] and sale["payment_method"] == "saldo", "el precio y el método los pone el servidor, no el cliente")

    # ================= A · DISPONIBILIDAD =================
    # Fuerza bruta en el login: bloqueo por IP + email
    attacker = S.Request(ip="66.66.66.66")
    for _ in range(5):
        await err(S.login(S.LoginIn(email="admin@weedlemon.es", password="mal"), attacker, S.Response()), 401)
    await err(S.login(S.LoginIn(email="admin@weedlemon.es", password="admin123"), attacker, S.Response()), 429)
    await S.login(S.LoginIn(email="admin@weedlemon.es", password="admin123"), S.Request(ip="10.1.1.1"), S.Response())
    check(True, "el bloqueo del atacante no deja fuera al administrador legítimo")
    # El atacante no se salta el bloqueo inventándose una IP en X-Forwarded-For
    spoof = S.Request(ip="10.0.0.2", headers={"x-forwarded-for": "1.2.3.4, 66.66.66.66"})
    check(S.client_ip(spoof) == "66.66.66.66", "se usa la IP que añade el proxy, no la que escribe el cliente")
    await err(S.login(S.LoginIn(email="admin@weedlemon.es", password="admin123"), spoof, S.Response()), 429)
    # Pasados los 15 minutos se puede volver a entrar (antes de la auditoría esto daba error 500 para siempre)
    from datetime import datetime, timedelta
    await db.login_attempts.update_one({"identifier": "66.66.66.66:admin@weedlemon.es"},
                                       {"$set": {"locked_until": datetime.utcnow() - timedelta(minutes=1)}})
    await S.login(S.LoginIn(email="admin@weedlemon.es", password="admin123"), attacker, S.Response())
    check(await db.login_attempts.find_one({"identifier": "66.66.66.66:admin@weedlemon.es"}) is None, "el bloqueo caduca y se limpia al entrar")

    # Límite de peticiones en los formularios públicos
    flood = S.Request(ip="77.77.77.77")
    for _ in range(120):
        await S.public_upload(flood, S.UploadFile("f.png", "image/png", PNG))
    await err(S.public_upload(flood, S.UploadFile("f.png", "image/png", PNG)), 429)

    # Subidas enormes: se cortan sin cargarlas enteras en memoria
    big = PNG + b"\0" * (8 * 1024 * 1024)
    await err(S.public_upload(S.Request(ip="8.8.4.4"), S.UploadFile("big.png", "image/png", big)), 400, "8 MB")
    await err(S.upload_legal_pdf(S.UploadFile("big.pdf", "application/pdf", b"%PDF" + b"\0" * (10 * 1024 * 1024)), user=admin), 400, "10 MB")

    # Búsquedas trampa (ReDoS): un patrón catastrófico se trata como texto y responde al instante
    t0 = time.time()
    await S.list_products(q="(a+)+$" + "a" * 50, category=None, active_only=False, user=cajero)
    await S.list_users(role=None, q="(x+x+)+y", user=admin)
    check(time.time() - t0 < 1, "las búsquedas con patrones catastróficos no bloquean el servidor")

    # Un único turno activo: el índice único impide dos aperturas simultáneas
    await S.cash_open(S.CashOpenIn(starting_amount=0), user=cajero)
    try:
        await db.cash_sessions.insert_one({"status": "opening", "active_lock": "local"})
        check(False, "se pudo crear un segundo turno activo")
    except S.DuplicateKeyError:
        check(True, "la base de datos impide un segundo turno activo")

    CHK.done()


if __name__ == "__main__":
    asyncio.run(main())
