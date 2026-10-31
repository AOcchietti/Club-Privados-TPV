"""Pruebas funcionales de punta a punta: productos, inventario, ventas y recargas (en turno y
fuera de turno), apertura y cierre de caja con recuentos, PDF, alta pública, usuarios y migraciones."""
import asyncio
import os
import tempfile
from datetime import date

from common import S, Checker, as_user, PNG

CHK = Checker("flujos")
check = CHK
expect_error = CHK.error


async def main():
    db = S.db
    # ----- arranque, seeds y migraciones -----
    await S.startup()
    await S.startup()  # idempotente
    admin = await as_user("admin@weedlemon.es")
    cajero = await as_user("cajero@weedlemon.es")
    check(admin.get("member_number") and cajero.get("member_number"), "el equipo tiene nº de socio")
    check(admin["balance"] == 0, "equipo con saldo 0")
    socios = await S.list_users(role="socio", q=None, user=admin)
    check(len(socios) == 3 and all(s["doc_number"] for s in socios), "socios seed con documento")
    lucia = next(s for s in socios if s["name"] == "Lucía")
    numbers = [u["member_number"] for u in await S.list_users(role=None, q=None, user=admin)]
    check(len(numbers) == len(set(numbers)), "nº de socio únicos")

    # login
    res = S.Response()
    out = await S.login(S.LoginIn(email="admin@weedlemon.es", password="admin123"), S.Request(), res)
    check("token" not in out and "access_token" in res.cookies, "login: el token solo viaja en la cookie httpOnly")

    # ----- productos e inventario -----
    cats = await S.list_categories(user=admin)
    p = await S.create_product(S.ProductCreate(name="Test Kush", category="indica", price=10, unit="g", initial_stock=10), user=cajero)
    pid = p["id"]
    check(p["stock"] == 10, "stock inicial")
    p = await S.update_product(pid, S.ProductUpdate(name="Test Kush", category="indica", price=11), user=cajero)
    check(p["stock"] == 10 and p["unit"] == "g" and p["price"] == 11, "editar no toca stock ni unidad")
    p = await S.stock_movement(pid, S.StockMoveIn(type="entrada", qty=5, reason="proveedor"), user=cajero)
    check(p["stock"] == 15, "entrada")
    p = await S.stock_movement(pid, S.StockMoveIn(type="merma", qty=3, reason="dañado"), user=cajero)
    check(p["stock"] == 12, "merma")
    p = await S.stock_movement(pid, S.StockMoveIn(type="ajuste", qty=-2, reason="recuento"), user=cajero)
    check(p["stock"] == 10, "ajuste")
    await expect_error(S.stock_movement(pid, S.StockMoveIn(type="merma", qty=20, reason="x"), user=cajero), 400, "negativo")
    await expect_error(S.stock_movement(pid, S.StockMoveIn(type="ajuste", qty=0, reason="x"), user=cajero), 400, "nada que ajustar")
    p = await S.stock_movement(pid, S.StockMoveIn(type="entrada", qty=1, reason="  "), user=cajero)
    check(p["stock"] == 11, "entrada sin motivo permitida")
    await expect_error(S.stock_movement(pid, S.StockMoveIn(type="merma", qty=1, reason=" "), user=cajero), 400, "obligatorio")
    await expect_error(S.stock_movement(pid, S.StockMoveIn(type="ajuste", qty=1, reason=""), user=cajero), 400, "obligatorio")
    p = await S.stock_movement(pid, S.StockMoveIn(type="merma", qty=1, reason="rota"), user=cajero)
    await expect_error(S.stock_movement(pid, S.StockMoveIn(type="robo", qty=1, reason="x"), user=cajero), 400)
    movs = await S.list_stock_movements(pid, user=admin)
    check(len(movs) == 6 and movs[0]["stock_after"] == 10, "historial de movimientos")
    check(any(m["type"] == "entrada" and m["reason"] is None for m in movs), "entrada sin motivo registrada")

    # categorías para comprobar el orden de secciones del recuento
    for label in ["Polen", "Dry Sift", "Hash", "Marihuana medicinal"]:
        c = await S.create_category(S.CategoryIn(label=label), user=admin)
        await S.create_product(S.ProductCreate(name=f"Prod {label}", category=c["key"], price=5, unit="g", initial_stock=3), user=admin)
    await expect_error(S.update_product("no-es-id", S.ProductUpdate(name="x", category="indica", price=1), user=admin), 404)

    # ----- ventas fuera de turno -----
    cur = await S.cash_current(user=cajero)
    check(cur["session"] is None and cur["out_of_shift_pending"]["count"] == 0, "sin turno")
    sale1 = await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=4)], socio_id=lucia["id"]), user=cajero)
    check(sale1["out_of_shift"] and sale1["out_of_shift_pending"] and sale1["cash_session_id"] is None, "venta fuera de turno")
    check((await db.products.find_one({"_id": S.oid(pid)}))["stock"] == 10, "fuera de turno no descuenta stock")
    check((await S.get_user(lucia["id"], user=admin))["balance"] == -44, "saldo descontado (deuda)")
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=7)], socio_id=lucia["id"]), user=cajero), 400, "stock insuficiente")
    sale2 = await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=3), S.SaleItemIn(product_id=pid, qty=2)], socio_id=lucia["id"]), user=cajero)
    check(sale2["total"] == 55, "segunda venta fuera de turno")
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1.5)], socio_id=lucia["id"]), user=cajero), 400, "quedan 1")
    cur = await S.cash_current(user=cajero)
    check(cur["out_of_shift_pending"] == {"count": 2, "total": 99.0, "recharges_count": 0, "recharges_total": 0}, "resumen pendientes")
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1)], socio_id=None), user=cajero), 400, "asigna un socio")
    r = await S.recharge_balance(lucia["id"], S.RechargeIn(amount=20), user=cajero)
    check(r["recharge_out_of_shift"] and r["balance"] == -79, "recarga fuera de turno: el saldo sube al momento")
    cur = await S.cash_current(user=cajero)
    check(cur["out_of_shift_pending"]["recharges_count"] == 1 and cur["out_of_shift_pending"]["recharges_total"] == 20, "recarga pendiente de incorporar")
    prods = {p["id"]: p for p in await S.list_products(q=None, category=None, active_only=True, user=cajero)}
    check(prods[pid]["available"] == 1 and prods[pid]["stock"] == 10, "available descuenta lo vendido fuera de turno")

    # ----- apertura -----
    sess = await S.cash_open(S.CashOpenIn(starting_amount=100), user=cajero)
    check(sess["status"] == "opening" and sess["out_of_shift_count"] == 2 and sess["out_of_shift_total"] == 99, "apertura absorbe ventas")
    check(sess["out_of_shift_recharge_count"] == 1 and sess["out_of_shift_recharge_total"] == 20, "apertura absorbe recargas")
    check((await db.recharges.find_one({"out_of_shift": True}))["session_id"] == sess["id"], "recarga asignada al turno")
    check((await db.products.find_one({"_id": S.oid(pid)}))["stock"] == 1, "stock descontado al abrir")
    check(all(not s["out_of_shift_pending"] for s in await db.sales.find({}).to_list(100)), "ventas ya no pendientes")
    await expect_error(S.cash_open(S.CashOpenIn(starting_amount=10), user=admin), 400, "ya hay")
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1)], socio_id=lucia["id"]), user=cajero), 400, "en pausa")
    await expect_error(S.stock_movement(pid, S.StockMoveIn(type="entrada", qty=1, reason="x"), user=cajero), 400, "bloqueados")
    await expect_error(S.recharge_balance(lucia["id"], S.RechargeIn(amount=20), user=cajero), 400, "en pausa")
    cur = await S.cash_current(user=cajero)
    st = cur["stocktake"]
    check(st and st["kind"] == "opening" and st["version"] == 1, "recuento de apertura creado")
    line = next(l for l in st["lines"] if l["product_id"] == pid)
    check(line["expected"] == 1 and line["counted"] is None, "esperado tras absorber")
    check(set(st["sections"]) == {l["category_label"] for l in st["lines"]}, "secciones = categorías")
    expected_order = ["Flor Índica", "Flor Sativa", "Marihuana medicinal", "Hash", "Extracto", "Dry Sift", "Polen", "Accesorio", "Comestible"]
    check(st["sections"] == expected_order, f"orden de secciones {st['sections']}")
    line_sections = []
    for l in st["lines"]:
        if not line_sections or line_sections[-1] != l["category_label"]:
            line_sections.append(l["category_label"])
    check(line_sections == expected_order, "líneas agrupadas en el mismo orden")

    # cancelar apertura (admin) restaura todo
    await expect_error(S.cash_closing_cancel(user=admin), 400, "ningún cierre")
    await S.cash_opening_cancel(user=admin)
    check((await db.products.find_one({"_id": S.oid(pid)}))["stock"] == 10, "cancelar apertura restaura stock")
    pend = (await S.cash_current(user=cajero))["out_of_shift_pending"]
    check(pend["count"] == 2 and pend["recharges_count"] == 1, "ventas y recargas vuelven a pendientes")
    check((await db.stocktakes.find_one({"session_id": sess["id"]}))["status"] == "cancelled", "recuento invalidado")

    sess = await S.cash_open(S.CashOpenIn(starting_amount=100), user=cajero)
    sid = sess["id"]
    otro = await S.create_user(S.UserCreate(name="Pepe", role="cajero", email="pepe@x.es", password="pepe1234"), user=admin)
    check(otro["member_number"].startswith("WL-"), "nuevo cajero con nº socio")
    pepe = await as_user("pepe@x.es")
    await expect_error(S.cash_opening_confirm(user=pepe), 403)
    await expect_error(S.cash_opening_confirm(user=cajero), 400, "pendientes de contar")
    st = (await S.cash_current(user=cajero))["stocktake"]
    v = st["version"]
    for section in st["sections"]:
        st = await S.cash_stocktake_autofill(S.AutofillIn(section=section, version=v), user=cajero)
        v = st["version"]
    check(all(l["counted"] == l["expected"] for l in st["lines"]), "autorrelleno por secciones")
    await expect_error(S.cash_stocktake_line(S.StocktakeLineIn(product_id=pid, counted=3, version=v - 1), user=cajero), 409)
    st = await S.cash_stocktake_line(S.StocktakeLineIn(product_id=pid, counted=0.5, version=v), user=admin)
    line = next(l for l in st["lines"] if l["product_id"] == pid)
    check(line["difference"] == -0.5, "diferencia registrada")
    await expect_error(S.cash_stocktake_line(S.StocktakeLineIn(product_id=pid, counted=-1, version=st["version"]), user=cajero), 400)
    await S.cash_opening_confirm(user=cajero)
    cur = await S.cash_current(user=cajero)
    check(cur["session"]["status"] == "open" and cur["stocktake"] is None, "turno abierto")
    check((await db.products.find_one({"_id": S.oid(pid)}))["stock"] == 0.5, "lo contado en la apertura pasa a ser el stock")
    rec = [m for m in await S.list_stock_movements(pid, user=admin) if m["type"] == "recuento"]
    check(len(rec) == 1 and rec[0]["qty"] == -0.5 and "apertura" in rec[0]["reason"], "movimiento de recuento registrado")
    others = await db.stock_movements.count_documents({"type": "recuento"})
    check(others == 1, "solo cambian los productos con diferencia")

    # ----- turno abierto -----
    await S.recharge_balance(lucia["id"], S.RechargeIn(amount=50), user=cajero)
    await expect_error(S.recharge_balance(lucia["id"], S.RechargeIn(amount=50, method="tarjeta"), user=cajero), 400, "efectivo")
    staff_rec = await S.recharge_balance(cajero["id"], S.RechargeIn(amount=10), user=admin)
    check(staff_rec["balance"] == 10, "recarga a miembro del equipo")
    p2 = await S.stock_movement(pid, S.StockMoveIn(type="entrada", qty=20, reason="proveedor"), user=cajero)
    check(p2["stock"] == 20.5, "entrada en turno abierto")
    sale3 = await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=2)], socio_id=lucia["id"]), user=pepe)
    check(not sale3["out_of_shift"] and sale3["cash_session_id"] == sid, "venta en turno")
    check((await db.products.find_one({"_id": S.oid(pid)}))["stock"] == 18.5, "venta en turno descuenta stock")
    staff_sale = await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1)], socio_id=cajero["id"]), user=admin)
    check(staff_sale["socio_member_number"] == cajero["member_number"], "el equipo puede comprar con su saldo")
    await S.cash_movement(S.CashMovementIn(type="in", amount=20, reason="cambio"), user=cajero)
    await expect_error(S.cash_movement(S.CashMovementIn(type="out", amount=500, reason="banco"), user=cajero), 400, "disponible")
    await expect_error(S.cash_movement(S.CashMovementIn(type="out", amount=5, reason=" "), user=cajero), 400, "motivo")
    await S.cash_movement(S.CashMovementIn(type="out", amount=30, reason="banco"), user=cajero)
    await expect_error(S.cash_movement(S.CashMovementIn(type="in", amount=5, reason="x"), user=pepe), 403)
    cur = await S.cash_current(user=cajero)
    t = cur["totals"]
    check(t["esperado"] == 170 and t["recargas_efectivo"] == 80 and t["entradas"] == 20 and t["salidas"] == 30, f"totales {t}")
    check(t["ventas_count"] == 4 and t["ventas_saldo"] == 99 + 22 + 11, f"ventas del turno incluyen absorbidas {t}")
    check(len(t["movements"]) == 2, "movimientos listados")

    # ----- cierre -----
    await expect_error(S.cash_closing_cash(S.ClosingCashIn(counted=1), user=cajero), 400, "inicia primero")
    await S.cash_closing_start(user=cajero)
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1)], socio_id=lucia["id"]), user=cajero), 400, "cierre")
    await expect_error(S.cash_closing_stocktake_start(user=cajero), 400, "arqueo")
    await expect_error(S.cash_closing_cash(S.ClosingCashIn(counted=None), user=cajero), 400)
    s = await S.cash_closing_cash(S.ClosingCashIn(counted=145, reason="faltan 5"), user=cajero)
    check(s["cash_count"]["difference"] == -25 and s["cash_count"]["expected"] == 170, "arqueo (la recarga fuera de turno cuenta en el esperado)")
    cur = await S.cash_current(user=cajero)
    check(cur["stocktake"] is None, "aún sin recuento de cierre")
    st = await S.cash_closing_stocktake_start(user=cajero)
    st_again = await S.cash_closing_stocktake_start(user=cajero)
    check(st["id"] == st_again["id"] and st["kind"] == "closing", "recuento de cierre idempotente")
    await expect_error(S.cash_closing_finalize(user=cajero), 400, "pendientes")
    v = st["version"]
    for l in st["lines"]:
        st = await S.cash_stocktake_autofill(S.AutofillIn(product_id=l["product_id"], version=v), user=cajero)
        v = st["version"]
    check(next(l for l in st["lines"] if l["product_id"] == pid)["expected"] == 17.5, "esperado de cierre")
    st = await S.cash_stocktake_line(S.StocktakeLineIn(product_id=pid, counted=17, version=v), user=cajero)
    closed = await S.cash_closing_finalize(user=cajero)
    check((await db.products.find_one({"_id": S.oid(pid)}))["stock"] == 17, "lo contado en el cierre pasa a ser el stock")
    check(closed["status"] == "closed" and closed["supervised"] is False and closed["difference"] == -25, "cierre final")
    check("active_lock" not in closed, "libera el turno activo")
    hist = await S.cash_sessions(user=admin)
    check(len(hist) == 1 and hist[0]["id"] == sid, "histórico de turnos")
    rep = await S.cash_session_report(sid, user=admin)
    check(len(rep["out_of_shift_sales"]) == 2 and rep["stocktake"]["kind"] == "closing" and rep["opening_stocktake"]["kind"] == "opening", "informe de turno")
    check(len(rep["out_of_shift_recharges"]) == 1 and rep["out_of_shift_recharges"][0]["amount"] == 20, "informe con recargas fuera de turno")
    hs = await S.list_sales(range="today", payment=None, socio_id=None, user=admin)
    check(len(hs) == 4, "histórico de ventas")

    # PDF del cierre
    pdf = await S.cash_session_pdf(sid, user=cajero)
    check(pdf.media_type == "application/pdf" and pdf.body.startswith(b"%PDF-1.4"), "PDF del cierre (responsable)")
    check("attachment" in pdf.headers["Content-Disposition"], "PDF como descarga")
    check(b"/Count 1" in pdf.body, "el PDF ocupa una sola página")
    check(b"de ellas fuera de turno \\(1\\)" in pdf.body, "el PDF refleja la recarga fuera de turno")
    check(b"Productos vendidos" not in pdf.body, "el PDF ya no lista los productos vendidos")
    open(os.path.join(tempfile.gettempdir(), "tpv-cierre-prueba.pdf"), "wb").write(pdf.body)
    await S.cash_session_pdf(sid, user=admin)
    await expect_error(S.cash_session_pdf(sid, user=pepe), 403)
    await expect_error(S.cash_session_pdf("zzz", user=admin), 404)

    # cancelar cierre y cierre supervisado por admin
    await S.cash_open(S.CashOpenIn(starting_amount=0), user=cajero)
    st = (await S.cash_current(user=cajero))["stocktake"]
    for section in st["sections"]:
        st = await S.cash_stocktake_autofill(S.AutofillIn(section=section, version=st["version"]), user=cajero)
    await S.cash_opening_confirm(user=cajero)
    open_sid = (await S.cash_current(user=cajero))["session"]["id"]
    await expect_error(S.cash_session_pdf(open_sid, user=admin), 400, "no está cerrado")
    await S.cash_closing_start(user=cajero)
    await S.cash_closing_cash(S.ClosingCashIn(counted=0), user=cajero)
    await S.cash_closing_stocktake_start(user=cajero)
    await S.cash_closing_cancel(user=admin)
    cur = await S.cash_current(user=cajero)
    check(cur["session"]["status"] == "open" and "cash_count" not in cur["session"], "cancelar cierre vuelve a abierto")
    await S.cash_closing_start(user=admin)
    await S.cash_closing_cash(S.ClosingCashIn(counted=0), user=admin)
    st = await S.cash_closing_stocktake_start(user=admin)
    check(st["status"] == "draft" and st["version"] == 1, "nuevo recuento tras cancelar")
    for section in st["sections"]:
        st = await S.cash_stocktake_autofill(S.AutofillIn(section=section, version=st["version"]), user=admin)
    closed = await S.cash_closing_finalize(user=admin)
    check(closed["supervised"] is True, "cierre supervisado por admin")

    # ----- alta pública -----
    legal = await S.public_legal()
    check(legal == {"available": False, "updated_at": None}, "sin acuerdo legal")
    req = S.Request(ip="10.0.0.1", headers={"x-forwarded-for": "88.1.1.1, 10.0.0.1"})
    await expect_error(S.public_upload(req, S.UploadFile("x.txt", "text/plain", b"hola")), 400, "imágenes")
    paths = {}
    for k in ["doc_photo", "face_photo", "signature"]:
        paths[k] = (await S.public_upload(req, S.UploadFile(f"{k}.png", "image/png", PNG)))["path"]
    check(all("/kyc/" in v for v in paths.values()), "subida pública")
    base = dict(name="Ana", apellidos="Pérez Ruiz", doc_type="NIE", doc_number="x-1234567-z", nationality="Italiana",
                birthdate="1995-04-02", phone="600000000", email=" Ana@Mail.com ", **paths)
    await expect_error(S.public_alta(S.PublicAltaIn(**base, legal_accepted=False), req), 400, "acuerdo")
    await expect_error(S.public_alta(S.PublicAltaIn(**{**base, "birthdate": f"{date.today().year - 17}-01-01"}, legal_accepted=True), req), 400, "mayor de edad")
    await expect_error(S.public_alta(S.PublicAltaIn(**{**base, "doc_number": "45678901-L"}, legal_accepted=True), req), 400, "documento")
    await expect_error(S.public_alta(S.PublicAltaIn(**{**base, "face_photo": "weedlemon/uploads/otra.png"}, legal_accepted=True), req), 400, "foto facial")
    await expect_error(S.public_alta(S.PublicAltaIn(**{**base, "apellidos": " "}, legal_accepted=True), req), 400, "apellidos")
    done = await S.public_alta(S.PublicAltaIn(**base, legal_accepted=True), req)
    check(set(done) == {"name", "member_number"} and done["member_number"].startswith("WL-"), "alta pública responde solo nombre y nº")
    ana = await db.users.find_one({"member_number": done["member_number"]})
    check(ana["status"] == "pendiente" and ana["doc_number"] == "X1234567Z" and ana["email"] == "ana@mail.com", "alta pendiente normalizada")
    await expect_error(S.public_alta(S.PublicAltaIn(**base, legal_accepted=True), req), 400, "documento")
    await S.cash_open(S.CashOpenIn(starting_amount=0), user=cajero)
    st = (await S.cash_current(user=cajero))["stocktake"]
    for section in st["sections"]:
        st = await S.cash_stocktake_autofill(S.AutofillIn(section=section, version=st["version"]), user=cajero)
    await S.cash_opening_confirm(user=cajero)
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1)], socio_id=str(ana["_id"])), user=cajero), 400, "pendiente")
    await S.update_user(str(ana["_id"]), S.UserUpdate(status="activa"), user=cajero)
    await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=pid, qty=1)], socio_id=str(ana["_id"])), user=cajero)

    # Carrera entre dos cajas: la venta leyó un stock que otra venta acaba de gastar.
    # El descuento condicional lo detecta y deshace lo ya descontado (atomicidad de la venta).
    other = (await db.products.find_one({"name": "Lemon Haze"}))
    stock_of = lambda doc_id: next(d for d in db.products.docs if d["_id"] == doc_id)["stock"]  # noqa: E731
    before_pid, before_other = stock_of(S.oid(pid)), stock_of(other["_id"])
    real_find_one = db.products.find_one

    async def stale_find_one(q=None, *a, **kw):
        doc = await real_find_one(q, *a, **kw)
        if doc:
            doc["stock"] = 10_000  # lectura "vieja"
        return doc
    db.products.find_one = stale_find_one
    await expect_error(S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=str(other["_id"]), qty=1),
                                                       S.SaleItemIn(product_id=pid, qty=before_pid + 5)],
                                                socio_id=str(ana["_id"])), user=cajero), 409, "acaba de venderlo")
    db.products.find_one = real_find_one
    check(stock_of(S.oid(pid)) == before_pid and stock_of(other["_id"]) == before_other, "venta rechazada sin descontar nada (rollback)")

    # acuerdo legal
    await expect_error(S.upload_legal_pdf(S.UploadFile("a.pdf", "application/pdf", b"no pdf"), user=admin), 400, "pdf")
    await S.upload_legal_pdf(S.UploadFile("acuerdo.pdf", "application/pdf", b"%PDF-1.4 test"), user=admin)
    legal = await S.public_legal()
    check(legal["available"] and legal["updated_at"], "acuerdo publicado")
    pdf = await S.public_legal_pdf()
    check(pdf.body.startswith(b"%PDF") and pdf.media_type == "application/pdf", "descarga del PDF")
    qr = await S.alta_qr(url="https://club.example/alta")
    check(qr.media_type == "image/png" and qr.body.startswith(b"\x89PNG"), "QR")
    await expect_error(S.alta_qr(url="javascript:alert(1)"), 400)

    # límite de peticiones
    for _ in range(3):
        await S.rate_limit(req, "t", limit=3)
    await expect_error(S.rate_limit(req, "t", limit=3), 429)
    await S.rate_limit(S.Request(ip="9.9.9.9"), "t", limit=3)

    # ----- usuarios -----
    soc = await S.create_user(S.UserCreate(name="Luis", apellidos="Gómez", doc_type="DNI", doc_number="11111111h", phone="1"), user=cajero)
    check(soc["doc_number"] == "11111111H" and soc["member_number"], "alta manual con documento")
    await expect_error(S.create_user(S.UserCreate(name="Otro", doc_number="11111111-H"), user=cajero), 400, "documento")
    await expect_error(S.update_user(soc["id"], S.UserUpdate(doc_number="45678901L"), user=cajero), 400, "documento")
    upd = await S.update_user(soc["id"], S.UserUpdate(doc_number="11111111H", nationality="Española", status="suspendida"), user=cajero)
    check(upd["nationality"] == "Española" and upd["status"] == "suspendida", "editar ficha")
    await expect_error(S.update_user(soc["id"], S.UserUpdate(status="rara"), user=cajero), 400)
    await expect_error(S.create_user(S.UserCreate(name="X", role="cajero", email="x@x", password="p"), user=cajero), 403)
    check(len(await S.list_users(role=None, q="pérez", user=admin)) == 1, "buscar por apellidos")
    check(len(await S.list_users(role=None, q="x1234567", user=admin)) == 1, "buscar por documento")
    check(isinstance(await S.list_users(role=None, q="(((", user=admin), list), "búsqueda con caracteres especiales")
    check(all(u["role"] == "socio" for u in await S.list_users(role=None, q=None, user=cajero)), "cajero solo ve socios")

    # ----- migración de datos antiguos -----
    await db.users.insert_one({"name": "Viejo", "role": "socio", "dni": "22222222-j", "status": "activa"})
    await S.migrate()
    viejo = await db.users.find_one({"name": "Viejo"})
    check(viejo["member_number"] and viejo["doc_number"] == "22222222J" and viejo["balance"] == 0, "migración de socio antiguo")

    stats = await S.dashboard_stats(user=admin)
    check(stats["today_count"] >= 5, "panel")

    # ----- reglas añadidas en la auditoría -----
    await expect_error(S.list_sales(range="all", payment=None, socio_id=None, user=cajero), 403, "administración")
    check(isinstance(await S.list_sales(range="all", payment=None, socio_id=lucia["id"], user=cajero), list), "el cajero ve las ventas de un socio")
    await expect_error(S.delete_user(lucia["id"], user=admin), 400, "saldo")
    sara = await db.users.find_one({"name": "Sara"})
    await S.delete_user(str(sara["_id"]), user=admin)
    await expect_error(S.create_user(S.UserCreate(name="Corto", role="cajero", email="c@x.es", password="corta"), user=admin), 400, "8 caracteres")
    # Los datos de ejemplo no reaparecen y la contraseña del admin no se pisa al reiniciar
    await S.update_user(admin["id"], S.UserUpdate(password="nuevaClaveSegura"), user=admin)
    await S.startup()
    check(await db.users.find_one({"name": "Sara"}) is None, "un socio de ejemplo borrado no reaparece")
    adm = await db.users.find_one({"email": "admin@weedlemon.es"})
    check(S.verify_password("nuevaClaveSegura", adm["password_hash"]), "la contraseña cambiada se mantiene tras reiniciar")
    os.environ["ADMIN_RESET_PASSWORD"] = "true"
    await S.startup()
    os.environ.pop("ADMIN_RESET_PASSWORD")
    adm = await db.users.find_one({"email": "admin@weedlemon.es"})
    check(S.verify_password("admin123", adm["password_hash"]), "restablecer la contraseña solo si se pide")
    CHK.done()


if __name__ == "__main__":
    asyncio.run(main())
