# Weed Lemon Social Club · TPV

Sistema de ventas para clubes privados: TPV con saldo de socios, caja por turnos con recuento de stock,
inventario, alta pública de socios con QR, histórico y auditoría.

- **Backend:** FastAPI + MongoDB (`backend/server.py`)
- **Frontend:** React (CRA + craco) + Tailwind + shadcn/ui (`frontend/`)
- Detalle funcional e historial de iteraciones: [`memory/PRD.md`](memory/PRD.md)

## Ejecutar en local

### Requisitos (una sola vez)

| Programa | Versión | Notas |
|---|---|---|
| Python | 3.12 o 3.13 | En Windows marca "Add python.exe to PATH" al instalar |
| Node.js | 20 LTS o 22 | Trae `npm` y `corepack` |
| Yarn 1 | 1.22 | `corepack enable` (o `npm install -g yarn`) |
| MongoDB Community Server | 7 u 8 | Instálalo "como servicio" y queda escuchando en `mongodb://localhost:27017`. Alternativa sin instalar nada: un cluster gratis de MongoDB Atlas |

### 1. Backend (terminal 1)

```bash
cd backend
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements-local.txt
cp .env.example .env        # Windows: copy .env.example .env
uvicorn server:app --reload --port 8001
```

Al arrancar por primera vez crea el administrador, un cajero, productos, categorías y socios de ejemplo.
Comprobación rápida: <http://localhost:8001/api/> debe responder `{"message": "Weed Lemon Social Club POS API"}`.

> Si PowerShell no deja activar el entorno: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a probar.

### 2. Frontend (terminal 2)

```bash
cd frontend
cp .env.example .env        # Windows: copy .env.example .env
yarn install
yarn start
```

Se abre <http://localhost:3000>.

### Usuarios de prueba

| Rol | Email | Contraseña |
|---|---|---|
| Administrador | `admin@weedlemon.es` | `admin123` |
| Cajero | `cajero@weedlemon.es` | `cajero123` |

El formulario público de alta de socios está en <http://localhost:3000/alta>.

### Notas

- En local las fotos y el PDF del acuerdo legal se guardan en `backend/uploads/` (no se sube a git).
  En Emergent se usa su almacenamiento si existe `EMERGENT_LLM_KEY`.
- `requirements.txt` es el entorno completo de Emergent; para local basta `requirements-local.txt`.
- Para empezar con la base de datos vacía, cambia `DB_NAME` en `backend/.env` (o borra la base desde MongoDB Compass).
- Si `yarn install` falla al descargar los paquetes `@emergentbase/...`, quita esas dos líneas de
  `devDependencies` en `frontend/package.json`: solo son herramientas de la preview de Emergent.
