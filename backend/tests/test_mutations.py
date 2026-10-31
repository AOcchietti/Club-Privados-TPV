"""Pruebas de mutación: ¿detectan las pruebas errores reales?

Se copia el backend, se le introduce A PROPÓSITO un error típico (una "mutación") y se vuelve a
ejecutar la simulación de invariantes. Si las pruebas son buenas, cada mutación debe hacerlas fallar.
Si alguna mutación pasara sin ser detectada, sería una zona del código sin vigilancia.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)

MUTATIONS = [
    ("La venta no descuenta el saldo del socio",
     '    await db.users.update_one({"_id": socio["_id"]}, {"$inc": {"balance": -total}})\n', "    pass\n"),
    ("El efectivo esperado olvida las recargas",
     'esperado = round(session.get("starting_amount", 0) + rec_efectivo + ventas_efectivo',
     'esperado = round(session.get("starting_amount", 0) + ventas_efectivo'),
    ("El recuento cambia el stock sin dejar rastro",
     'record_stock_movement(product, "recuento", round(l["counted"] - before, 3), before,',
     'record_stock_movement(product, "recuento", 0, before,'),
    ("Cancelar una apertura no devuelve las recargas fuera de turno",
     '    if rec_ids:\n        await db.recharges.update_many', '    if False:\n        await db.recharges.update_many'),
    ("Las mermas ignoran lo vendido fuera de turno",
     'reserved = (await pending_out_of_shift_qty()).get(str(product["_id"]), 0)', 'reserved = 0'),
    ("La apertura no marca como incorporadas las ventas fuera de turno",
     '"out_of_shift_pending": False, "cash_session_id": sid, "absorbed_at": now_utc()}})',
     '"cash_session_id": sid, "absorbed_at": now_utc()}})'),
    ("Se permite vender más de lo que hay en stock",
     '        if available < qty - 1e-9:', '        if False:'),
    ("Se venden y se mueven fracciones de productos por unidades",
     '    if product.get("unit") == "ud" and not is_whole(qty):', '    if False:'),
    ("Filtrar por una categoría madre olvida sus subcategorías",
     'query["category"] = {"$in": await category_and_children(category)}', 'query["category"] = category', "test_flows.py"),
    ("Rellenar lo pendiente pisa lo que ya estaba contado",
     '            if body.only_pending and l["counted"] is not None:\n                continue\n', '', "test_flows.py"),
    ("El PDF trata igual los productos caros y los baratos",
     'return GRAM_MIN_PREMIUM if price >= PREMIUM_PRICE else GRAM_MIN_CHEAP', 'return GRAM_MIN_CHEAP',
     "test_flows.py", "cierre_pdf.py"),
    ("El PDF no oculta las diferencias pequeñas",
     '        return 1e-9\n    price = line.get("price")', '        return 1e-9\n    return 1e-9\n    price = line.get("price")',
     "test_flows.py", "cierre_pdf.py"),
    # --- mutaciones de seguridad: se comprueban con test_security.py ---
    ("[seguridad] Cerrar sesión no anula el token (una cookie copiada sigue valiendo)",
     '        if await is_revoked(payload):  # sesión cerrada', '        if False:  # sesión cerrada', "test_security.py"),
    ("[seguridad] Contraseñas largas rompen el login con bcrypt 5",
     'return (password or "").encode("utf-8")[:BCRYPT_MAX_BYTES]', 'return (password or "").encode("utf-8")', "test_security.py"),
    ("[seguridad] Sin protección CSRF",
     'if headers.get(b"x-requested-with", b"").lower() != b"xmlhttprequest":', 'if False:', "test_security.py"),
    ("[seguridad] Se aceptan archivos que no son imágenes (SVG/HTML)",
     '    for sig, ctype in IMAGE_SIGNATURES:', '    return "image/png"\n    for sig, ctype in IMAGE_SIGNATURES:', "test_security.py"),
    ("[seguridad] Una cuenta suspendida sigue entrando con su token",
     'if user.get("role") not in STAFF_ROLES or user.get("status") in ("suspendida", "pendiente"):\n            raise HTTPException(status_code=401, detail="Cuenta sin acceso")',
     'if False:\n            raise HTTPException(status_code=401, detail="Cuenta sin acceso")', "test_security.py"),
    ("[seguridad] La IP se toma de la parte que escribe el cliente",
     'last = fwd.split(",")[-1].strip()', 'last = fwd.split(",")[0].strip()', "test_security.py"),
    ("[seguridad] Búsqueda sin escapar (inyección de patrones)",
     'query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}', 'query["name"] = {"$regex": q, "$options": "i"}', "test_security.py"),
    ("[seguridad] El cajero puede ver el histórico completo de ventas",
     'if user["role"] != "admin" and not socio_id:', 'if False:', "test_security.py"),
]


def main():
    caught = 0
    for name, old, new, *rest in MUTATIONS:
        suite = rest[0] if rest else "test_invariants.py"
        target = rest[1] if len(rest) > 1 else "server.py"
        tmp = tempfile.mkdtemp(prefix="tpv-mutante-")
        for f in os.listdir(BACKEND):
            if f.endswith(".py"):
                shutil.copy(os.path.join(BACKEND, f), tmp)
        src = open(os.path.join(tmp, target), encoding="utf-8").read()
        assert src.count(old) == 1, f"la mutación «{name}» ya no encaja con el código"
        open(os.path.join(tmp, target), "w", encoding="utf-8").write(src.replace(old, new))
        env = dict(os.environ, TPV_BACKEND_DIR=tmp)
        args = ["1", "2", "3"] if suite == "test_invariants.py" else []
        res = subprocess.run([sys.executable, os.path.join(HERE, suite), *args],
                             env=env, capture_output=True, text=True, timeout=600)
        if "SyntaxError" in res.stderr or "IndentationError" in res.stderr:
            raise SystemExit(f"La mutación «{name}» rompe la sintaxis: corrígela")
        detected = res.returncode != 0 and "AssertionError" in res.stderr
        caught += detected
        detail = res.stderr.strip().splitlines()[-1][:110] if detected else "¡NO DETECTADA!"
        print(f"   {'detectada' if detected else 'ESCAPA   '} · {name}\n               → {detail}")
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"OK · mutaciones: {caught}/{len(MUTATIONS)} errores introducidos detectados")
    if caught != len(MUTATIONS):
        sys.exit(1)


if __name__ == "__main__":
    main()
