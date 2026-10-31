"""Ejecuta todas las pruebas del backend.

    cd backend
    python tests/run_all.py

No necesita MongoDB ni el servidor arrancado: usa una base de datos en memoria.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [
    ("Funcionales (flujos completos)", "test_flows.py"),
    ("Seguridad (tríada CIA)", "test_security.py"),
    ("Consistencia (simulación aleatoria)", "test_invariants.py"),
    ("Mutación (¿las pruebas detectan errores?)", "test_mutations.py"),
]

failed = 0
for title, script in SUITES:
    t0 = time.time()
    res = subprocess.run([sys.executable, os.path.join(HERE, script)], capture_output=True, text=True)
    lines = [l for l in res.stdout.splitlines() if l.strip()]
    ok = res.returncode == 0
    failed += not ok
    print(f"{'✔' if ok else '✘'} {title} · {time.time() - t0:.1f} s")
    for l in lines:
        print("   " + l)
    if not ok:
        print("\n".join("   " + l for l in res.stderr.strip().splitlines()[-8:]))
print("\nTodo correcto." if not failed else f"\n{failed} bloque(s) con fallos.")
sys.exit(1 if failed else 0)
