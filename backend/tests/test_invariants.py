"""Pruebas de consistencia (integridad) con simulación aleatoria.

Se lanzan miles de operaciones al azar, como haría el personal del club a lo largo de muchos días:
ventas y recargas (con y sin turno), entradas/mermas/ajustes de stock, movimientos de caja,
aperturas y cierres con recuentos que no cuadran, cancelaciones, productos que se desactivan…
Muchas operaciones fallan a propósito (stock insuficiente, caja en cierre, etc.): eso está bien.
Lo importante es que DESPUÉS DE CADA OPERACIÓN se cumplen siempre estas reglas (invariantes):

  I1  Como mucho un turno activo a la vez.
  I2  Ningún producto tiene stock negativo.
  I3  Libro de stock: stock = stock inicial + movimientos registrados − lo vendido ya descontado.
  I4  Libro de saldos: saldo de cada persona = sus recargas − sus compras.
  I5  Cada venta/recarga está o pendiente fuera de turno o en un turno real (nunca en uno cancelado).
  I6  Cada turno cerrado: esperado = fondo + recargas + entradas − salidas; diferencia = contado − esperado.
  I7  Números de ticket y de socio únicos.
  I8  Como mucho un recuento en borrador por turno y tipo; los recuentos finales están completos.
  I9  "available" = stock − lo vendido fuera de turno pendiente, y nunca es negativo.
  I10 El efectivo esperado de un turno abierto nunca es negativo.
"""
import asyncio
import random
import sys

from common import S, Checker, as_user, HTTPException

CHK = Checker("invariantes")
EPS = 1e-6


def docs(col):
    return getattr(S.db, col).docs


async def check_invariants(base_stock, step):
    where = f"(paso {step})"
    sessions = docs("cash_sessions")
    active = [s for s in sessions if s["status"] in S.ACTIVE_STATUSES]
    CHK(len(active) <= 1, f"I1 un único turno activo {where}")

    products = {str(p["_id"]): p for p in docs("products")}
    for pid, p in products.items():
        CHK(p.get("stock", 0) >= -EPS, f"I2 stock negativo en {p['name']}: {p['stock']} {where}")

    sales = docs("sales")
    sold_applied = {}
    for s_ in sales:
        if not s_.get("out_of_shift_pending"):
            for it in s_["items"]:
                sold_applied[it["product_id"]] = sold_applied.get(it["product_id"], 0) + it["qty"]
    moves = {}
    for m in docs("stock_movements"):
        moves[m["product_id"]] = moves.get(m["product_id"], 0) + m["qty"]
    for pid, p in products.items():
        expected = base_stock.get(pid, 0) + moves.get(pid, 0) - sold_applied.get(pid, 0)
        CHK(abs(p["stock"] - expected) < 1e-3, f"I3 libro de stock de {p['name']}: {p['stock']} ≠ {expected} {where}")

    paid, spent = {}, {}
    for r in docs("recharges"):
        paid[r["socio_id"]] = paid.get(r["socio_id"], 0) + r["amount"]
    for s_ in sales:
        spent[s_["socio_id"]] = spent.get(s_["socio_id"], 0) + s_["total"]
    for u in docs("users"):
        uid = str(u["_id"])
        CHK(abs((u.get("balance") or 0) - (paid.get(uid, 0) - spent.get(uid, 0))) < 0.01,
            f"I4 saldo de {u['name']}: {u.get('balance')} ≠ {paid.get(uid, 0) - spent.get(uid, 0)} {where}")

    by_id = {str(s["_id"]): s for s in sessions}
    for s_ in sales:
        if s_.get("out_of_shift_pending"):
            CHK(s_.get("cash_session_id") is None, f"I5 venta pendiente con turno {where}")
        else:
            sess = by_id.get(s_.get("cash_session_id"))
            CHK(sess is not None and sess["status"] != "cancelled", f"I5 venta {s_['ticket_number']} sin turno válido {where}")
    for r in docs("recharges"):
        if r.get("out_of_shift_pending"):
            CHK(r.get("session_id") is None, f"I5 recarga pendiente con turno {where}")
        else:
            sess = by_id.get(r.get("session_id"))
            CHK(sess is not None and sess["status"] != "cancelled", f"I5 recarga sin turno válido {where}")

    for sess in sessions:
        sid = str(sess["_id"])
        rec = sum(r["amount"] for r in docs("recharges") if r.get("session_id") == sid)
        mv = [m for m in docs("cash_movements") if m["session_id"] == sid]
        esperado = sess["starting_amount"] + rec + sum(m["amount"] for m in mv if m["type"] == "in") - sum(m["amount"] for m in mv if m["type"] == "out")
        if sess["status"] == "closed":
            CHK(abs(sess["expected_amount"] - esperado) < 0.01, f"I6 esperado del turno {sess['expected_amount']} ≠ {esperado} {where}")
            CHK(abs(sess["difference"] - (sess["counted_amount"] - sess["expected_amount"])) < 0.01, f"I6 diferencia {where}")
        if sess["status"] == "open":
            CHK(esperado >= -0.01, f"I10 efectivo esperado negativo {esperado} {where}")

    tickets = [s_["ticket_number"] for s_ in sales]
    CHK(len(tickets) == len(set(tickets)), f"I7 tickets duplicados {where}")
    members = [u["member_number"] for u in docs("users") if u.get("member_number")]
    CHK(len(members) == len(set(members)), f"I7 nº de socio duplicados {where}")

    drafts = {}
    for st in docs("stocktakes"):
        if st["status"] == "draft":
            key = (st["session_id"], st["kind"])
            drafts[key] = drafts.get(key, 0) + 1
        if st["status"] == "final":
            CHK(all(l["counted"] is not None for l in st["lines"]), f"I8 recuento final incompleto {where}")
    CHK(all(v <= 1 for v in drafts.values()), f"I8 dos recuentos en borrador {where}")

    reserved = {}
    for s_ in sales:
        if s_.get("out_of_shift_pending"):
            for it in s_["items"]:
                reserved[it["product_id"]] = reserved.get(it["product_id"], 0) + it["qty"]
    for pid, p in products.items():
        CHK(p["stock"] - reserved.get(pid, 0) >= -1e-3, f"I9 available negativo en {p['name']} {where}")


async def simulate(seed, steps):
    rnd = random.Random(seed)
    S.db.cols.clear()  # base de datos vacía en cada semilla
    await S.startup()
    admin = await as_user("admin@weedlemon.es")
    cajero = await as_user("cajero@weedlemon.es")
    otro = await S.create_user(S.UserCreate(name="Otro cajero", role="cajero", email=f"otro{seed}@x.es", password="clave-larga-1"), user=admin)
    otro = await as_user(otro["email"])
    staff = [admin, cajero, otro]
    for i in range(4):
        await S.create_user(S.UserCreate(name=f"Socio {i}", doc_number=f"{seed}{i}0000000X"), user=admin)
    base_stock = {str(p["_id"]): p["stock"] for p in docs("products")}  # productos de ejemplo (sin movimiento de alta)
    stats = {"ok": 0, "rechazadas": 0}

    async def refresh(u):
        return await as_user(u["email"])

    def members():
        return [u for u in docs("users") if u.get("member_number") and u.get("status") == "activa"]

    def prods():
        return [p for p in docs("products")]

    for step in range(steps):
        actor = rnd.choice(staff)
        actor = await refresh(actor)
        session = await S.get_active_session()
        op = rnd.random()
        if session and session["status"] in ("opening", "closing") and rnd.random() < 0.6:
            op = 0.70  # en mitad de una apertura/cierre, lo normal es terminarla
        if op >= 0.84 and op < 0.88 and rnd.random() < 0.7:
            op = 0.10  # desactivar productos es poco frecuente: se convierte en venta
        try:
            if op < 0.30:  # venta
                items = []
                for p in rnd.sample(prods(), k=min(len(prods()), rnd.randint(1, 3))):
                    items.append(S.SaleItemIn(product_id=str(p["_id"]), qty=rnd.choice([0.5, 1, 2, 3.5, 7])))
                socio = rnd.choice(members())
                await S.create_sale(S.SaleCreate(items=items, socio_id=str(socio["_id"])), user=actor)
            elif op < 0.42:  # recarga
                socio = rnd.choice(members())
                await S.recharge_balance(str(socio["_id"]), S.RechargeIn(amount=rnd.choice([5, 10, 20, 50, 1001])), user=actor)
            elif op < 0.52:  # movimiento de stock
                reserved = await S.pending_out_of_shift_qty()
                if reserved and rnd.random() < 0.4:
                    # Ataque a la consistencia: intentar dar de baja stock ya vendido fuera de turno
                    pid = rnd.choice(list(reserved))
                    p = next((x for x in prods() if str(x["_id"]) == pid), None)
                    if p is not None:
                        eat = round(p["stock"] - reserved[pid] + 0.5, 3)
                        if eat > 0:
                            await S.stock_movement(pid, S.StockMoveIn(type="merma", qty=eat, reason="prueba"), user=actor)
                else:
                    p = rnd.choice(prods())
                    t = rnd.choice(["entrada", "merma", "ajuste"])
                    qty = rnd.choice([1, 2, 5, 20]) if t != "ajuste" else rnd.choice([-5, -1, 1, 3])
                    await S.stock_movement(str(p["_id"]), S.StockMoveIn(type=t, qty=qty, reason="prueba" if t != "entrada" else ""), user=actor)
            elif op < 0.58:  # movimiento de caja
                await S.cash_movement(S.CashMovementIn(type=rnd.choice(["in", "out"]), amount=rnd.choice([5, 20, 80, 500]), reason="prueba"), user=actor)
            elif op < 0.66:  # abrir turno
                await S.cash_open(S.CashOpenIn(starting_amount=rnd.choice([0, 50, 100])), user=actor)
            elif op < 0.80:  # contar / confirmar apertura o avanzar el cierre
                if session and session["status"] in ("opening", "closing"):
                    st = await S.get_draft_stocktake(session)
                    if session["status"] == "closing" and not session.get("cash_count"):
                        await S.cash_closing_cash(S.ClosingCashIn(counted=rnd.choice([0, 50, 100, 150])), user=actor)
                    elif not st:
                        await S.cash_closing_stocktake_start(user=actor)
                    else:
                        st = S.ser(st)
                        for line in st["lines"]:
                            counted = line["expected"] if rnd.random() < 0.8 else max(0, line["expected"] + rnd.choice([-2, -0.5, 1]))
                            st = await S.cash_stocktake_line(S.StocktakeLineIn(product_id=line["product_id"], counted=counted, version=st["version"]), user=actor)
                        if session["status"] == "opening":
                            await S.cash_opening_confirm(user=actor)
                        else:
                            await S.cash_closing_finalize(user=actor)
                elif session and session["status"] == "open":
                    await S.cash_closing_start(user=actor)
            elif op < 0.84:  # cancelaciones (solo administración)
                if session and session["status"] == "opening":
                    await S.cash_opening_cancel(user=admin)
                elif session and session["status"] == "closing":
                    await S.cash_closing_cancel(user=admin)
            elif op < 0.88:  # activar / desactivar producto (los inactivos se reactivan antes)
                inactive = [p for p in prods() if not p.get("active", True)]
                p = rnd.choice(inactive) if inactive and rnd.random() < 0.7 else rnd.choice(prods())
                await S.toggle_product(str(p["_id"]), user=actor)
            elif op < 0.90:  # producto nuevo
                p = await S.create_product(S.ProductCreate(name=f"Nuevo {step}", category="sativa", price=rnd.choice([5, 8.5]), unit="g",
                                                           initial_stock=rnd.choice([0, 3, 10])), user=actor)
            elif op < 0.93:  # recuento con versión caducada (dos dispositivos a la vez)
                if session and session["status"] in ("opening", "closing"):
                    st = await S.get_draft_stocktake(session)
                    if st and st["lines"]:
                        await S.cash_stocktake_line(S.StocktakeLineIn(product_id=st["lines"][0]["product_id"], counted=1, version=st["version"] - 1), user=actor)
            else:  # intento de venta a socio pendiente o con cantidad absurda
                await S.create_sale(S.SaleCreate(items=[S.SaleItemIn(product_id=str(rnd.choice(prods())["_id"]), qty=rnd.choice([-1, 0, 10**7]))],
                                                 socio_id=str(rnd.choice(members())["_id"])), user=actor)
            stats["ok"] += 1
        except HTTPException as e:
            if e.status_code >= 500:
                raise
            stats["rechazadas"] += 1
        await check_invariants(base_stock, step)
    closed = sum(1 for s in docs("cash_sessions") if s["status"] == "closed")
    print(f"   semilla {seed}: {steps} operaciones · {stats['ok']} aceptadas · {stats['rechazadas']} rechazadas por las reglas · "
          f"{closed} turnos cerrados · {len(docs('sales'))} ventas · {len(docs('recharges'))} recargas")


async def main():
    seeds = [int(a) for a in sys.argv[1:]] or [1, 2, 3, 4, 5]
    for seed in seeds:
        await simulate(seed, 1500)
    CHK.done()


if __name__ == "__main__":
    asyncio.run(main())
