# Despliegue en un servidor real

La app (frontend) y la API (backend) se publican juntas en **un solo servicio** con el `Dockerfile` de la raíz.
Comparten dirección, así que no hacen falta CORS ni cookies de terceros (que Safari bloquea). Fotos y PDF se guardan
dentro de MongoDB (`FILE_STORAGE=mongo`), de modo que el servidor no necesita disco permanente.

Recomendado para la demo: **MongoDB Atlas** (base de datos, plan gratis) + **Render** (servidor, `render.yaml` incluido).

## 1. Base de datos: MongoDB Atlas

1. Crea un clúster **Free** en una región europea (Frankfurt o París).
2. *Database Access* → usuario con contraseña larga.
3. *Network Access* → `0.0.0.0/0` (Render no tiene IP fija en los planes pequeños; la protección es la contraseña).
4. *Connect → Drivers* → copia la cadena `mongodb+srv://usuario:contraseña@…`.
5. Activa las copias diarias (*Backup*).

Límites del plan gratis: 0,5 GB, 100 operaciones/s, MongoDB 8. Las pruebas de GitHub usan MongoDB 8.

## 2. Servidor: Render

1. Entra en Render con GitHub. La cuenta dueña del repositorio tiene que autorizar el acceso.
2. *New → Blueprint* → repositorio `Club-Privados-TPV`. Render lee `render.yaml` (rama `demo`).
3. Rellena:
   - `MONGO_URL`: la cadena de Atlas.
   - `ADMIN_PASSWORD`: contraseña nueva del administrador (nunca `admin123`).
   - `FRONTEND_URL`: la dirección pública, p. ej. `https://weedlemon-tpv.onrender.com` (se puede poner después).
   - `JWT_SECRET` lo genera Render.
4. El primer despliegue tarda unos 5–8 minutos. Después, cada push a `demo` se publica solo **si las pruebas de
   GitHub pasan** (`autoDeployTrigger: checksPass`).

Plan: `starter` (siempre encendido) viene por defecto. Con `free` el servicio se duerme tras 15 minutos sin uso y
tarda cerca de un minuto en despertar: ábrelo un par de minutos antes de presentar.

## 3. Nada más publicarlo

1. Entra con `admin@weedlemon.es` y tu contraseña.
2. *Socios y equipo* → cambia la contraseña del cajero (`cajero123` está en el repositorio, que es público).
3. Sube el PDF del acuerdo legal y prueba el alta por QR desde un móvil (la cámara necesita HTTPS, que Render pone).

## Variables de entorno

| Variable | Para qué | En Render |
|---|---|---|
| `MONGO_URL`, `DB_NAME` | Conexión a MongoDB | Obligatorias |
| `JWT_SECRET` | Firma de las sesiones; en producción el servidor **no arranca** si tiene menos de 32 caracteres | Generada |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Administrador que se crea en el primer arranque | Obligatorias |
| `FRONTEND_URL` | Origen permitido por CORS | Recomendada |
| `FILE_STORAGE` | `mongo` (por defecto en el Dockerfile), `local` o `emergent` | No tocar |
| `COOKIE_SAMESITE` | `lax` por defecto en el Dockerfile (app y API en la misma web) | No tocar |
| `ADMIN_RESET_PASSWORD` | `true` solo para recuperar la contraseña del admin; quitar después | — |

## Probar la imagen en tu ordenador (opcional)

Con Docker Desktop y MongoDB local:

```bash
docker build -t tpv .
docker run -p 8000:8000 -e MONGO_URL=mongodb://host.docker.internal:27017 -e DB_NAME=tpv_docker \
  -e JWT_SECRET=una-frase-aleatoria-de-al-menos-32-caracteres -e COOKIE_SECURE=false tpv
```

Abre <http://localhost:8000>.

## Comprobarlo contra el servidor

`backend/tests/e2e_real.py` recorre la app por HTTP (login, CSRF, subidas, turnos, ventas simultáneas, PDF…).
**Escribe datos**: úsalo solo con una base de datos de pruebas.

```bash
cd backend
python tests/e2e_real.py http://localhost:8000 --si
```

GitHub ya lo ejecuta en cada push (pestaña *Actions*), junto con la imagen Docker, un navegador real y `pip-audit`.
