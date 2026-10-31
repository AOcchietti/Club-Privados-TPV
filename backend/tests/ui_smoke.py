"""Prueba con un navegador real (Chromium) contra el servidor desplegado: login, TPV, Caja y Gestión.

    pip install playwright && python -m playwright install chromium
    python tests/ui_smoke.py http://localhost:8080

Comprueba también que la app no pide nada a terceros (ni Google Fonts ni analítica): todo sale del mismo servidor.
"""
import os
import re
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

GHA = os.environ.get("GITHUB_ACTIONS") == "true"


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

        terceros = sorted(h for h in hosts if h and h != host)
        check(not terceros, f"ninguna petición a terceros ({terceros or 'solo ' + host})")
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
        print(f"::notice title=Navegador real::{n} comprobaciones correctas (login, TPV, Caja, Gestión, sin terceros)")
