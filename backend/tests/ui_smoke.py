"""Prueba con un navegador real (Chromium) contra el servidor desplegado: login, TPV, Caja y Gestión.

    pip install playwright && python -m playwright install chromium
    python tests/ui_smoke.py http://localhost:8080

Comprueba también que la app no pide nada a terceros (ni Google Fonts ni analítica): todo sale del mismo servidor.
"""
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

GHA = os.environ.get("GITHUB_ACTIONS") == "true"
# Las fotos de los 10 productos de ejemplo se enlazan desde Pexels. Desaparecen al subir fotos propias desde Gestión.
FOTOS_DE_EJEMPLO = {"images.pexels.com"}


def main(base):
    host = urlparse(base).hostname
    checks = []

    def check(cond, msg):
        if not cond:
            raise AssertionError(msg)
        checks.append(msg)
        print(f"  ✔ {msg}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 860})
        hosts, errors = set(), []
        page.on("request", lambda r: hosts.add(urlparse(r.url).hostname))
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Recuperación de contraseña desde las pantallas (con Mailpit si está disponible)
        api = (os.environ.get("MAILPIT_URL") or "").rstrip("/")
        antes = {m["ID"] for m in (requests.get(f"{api}/api/v1/messages", timeout=10).json().get("messages") or [])} if api else set()
        page.goto(base + "/login")
        page.click('[data-testid="login-forgot-link"]')
        page.fill('[data-testid="forgot-email-input"]', "cajero@weedlemon.es")
        page.click('[data-testid="forgot-submit-button"]')
        page.wait_for_selector('[data-testid="forgot-sent"]', timeout=10000)
        check(True, "pedir el enlace desde «¿Has olvidado tu contraseña?»")
        if api:
            link = None
            for _ in range(40):
                for m in requests.get(f"{api}/api/v1/messages", timeout=10).json().get("messages") or []:
                    if m["ID"] not in antes and "Cambia tu contraseña" in m.get("Subject", ""):
                        texto = requests.get(f"{api}/api/v1/message/{m['ID']}", timeout=10).json().get("Text", "")
                        found = re.search(r"/restablecer\?token=[\w-]+", texto)
                        link = found.group(0) if found else None
                        if link:  # el más reciente (Mailpit los devuelve de nuevo a viejo)
                            break
                if link:
                    break
                time.sleep(1)
            check(link is not None, "llega el correo con el enlace")
            page.goto(base + link)
            page.wait_for_selector('[data-testid="reset-password-input"]', timeout=10000)
            check("token=" not in page.url, "el token desaparece de la barra de direcciones")
            page.fill('[data-testid="reset-password-input"]', "clave-navegador-123")
            page.fill('[data-testid="reset-password-repeat"]', "clave-navegador-123")
            page.click('[data-testid="reset-submit-button"]')
            page.wait_for_selector('[data-testid="reset-done"]', timeout=10000)
            check(True, "contraseña cambiada desde el enlace del correo")

        page.goto(base + "/login")
        page.fill('[data-testid="login-email-input"]', os.environ.get("E2E_ADMIN_EMAIL", "admin@weedlemon.es"))
        page.fill('[data-testid="login-password-input"]', os.environ.get("E2E_ADMIN_PASSWORD", "admin123"))
        page.click('[data-testid="login-submit-button"]')
        page.wait_for_url(re.compile(r"^(?!.*/login).*$"), timeout=15000)
        check(True, "login desde el formulario (cookies de sesión aceptadas por el navegador)")

        page.goto(base + "/tpv")
        page.wait_for_selector('[data-testid="pos-page"]', timeout=15000)
        page.wait_for_selector('[data-testid^="pos-product-card-"]', timeout=15000)
        cards = page.locator('[data-testid^="pos-product-card-"]')
        check(cards.count() > 0, f"el TPV muestra {cards.count()} productos")
        cards.first.click()
        page.wait_for_selector('[data-testid^="cart-item-"]', timeout=5000)
        check(True, "añadir un producto al ticket")
        check(page.evaluate("document.fonts.check('700 16px Outfit')"), "tipografías cargadas desde la propia app")

        page.goto(base + "/caja")
        page.wait_for_selector('[data-testid="caja-page"]', timeout=15000)
        check(True, "pantalla de Caja")
        page.goto(base + "/gestion")
        page.wait_for_selector('[data-testid="gestion-page"]', timeout=15000)
        check(True, "pantalla de Gestión")
        page.screenshot(path="tpv-navegador.png", full_page=True)

        terceros = sorted(h for h in hosts if h and h != host and h not in FOTOS_DE_EJEMPLO)
        check(not terceros, f"ninguna petición a terceros salvo las fotos de ejemplo ({terceros or 'solo ' + host})")
        if hosts & FOTOS_DE_EJEMPLO:
            print("  · aviso: las fotos de los productos de ejemplo se cargan desde Pexels")
        check(not errors, f"sin errores de JavaScript ({errors[:2]})")
        browser.close()
    return len(checks)


if __name__ == "__main__":
    try:
        n = main(sys.argv[1].rstrip("/"))
    except Exception as e:  # noqa: BLE001
        print(f"\n✘ FALLO: {e}")
        if GHA:
            print(f"::error title=Navegador real::{str(e)[:900]}")
        sys.exit(1)
    print(f"\nOK · navegador: {n} comprobaciones")
    if GHA:
        print(f"::notice title=Navegador real::{n} comprobaciones correctas (recuperar contraseña, login, TPV, Caja, Gestión, sin terceros)")
