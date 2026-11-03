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
2. *New → Blueprint* → repositorio `Club-Privados-TPV`. Render lee `render.yaml` (rama `main`, la versión estable).
3. Rellena:
   - `MONGO_URL`: la cadena de Atlas.
   - `ADMIN_PASSWORD`: contraseña nueva del administrador (nunca `admin123`).
   - `FRONTEND_URL`: la dirección pública, p. ej. `https://weedlemon-tpv.onrender.com`. La usan los enlaces de los correos.
   - `BREVO_API_KEY` y `EMAIL_FROM`: el correo de recuperación de contraseña (apartado siguiente). Se pueden dejar vacíos y ponerlos después.
   - `JWT_SECRET` lo genera Render.
4. El primer despliegue tarda unos 5–8 minutos. Después, cada cambio que llega a `main` se publica solo **si las
   pruebas de GitHub pasan** (`autoDeployTrigger: checksPass`).

Plan: `starter` (siempre encendido) viene por defecto. Con `free` el servicio se duerme tras 15 minutos sin uso y
tarda cerca de un minuto en despertar: ábrelo un par de minutos antes de presentar.

## 3. Correo para recuperar contraseñas

Desde «¿Has olvidado tu contraseña?» en el acceso, el equipo recibe un enlace de un solo uso que caduca en 30 minutos.
El plan gratis de Render **bloquea el correo por SMTP** (puertos 25, 465 y 587), así que hay dos caminos:

| Opción | Sirve en | Qué configurar |
|---|---|---|
| **Brevo** (recomendado) | Cualquier plan, también el gratis | Cuenta gratis en Brevo (300 correos/día), verificar el remitente en *Senders*, crear una clave en *SMTP & API → API Keys*. Variables `BREVO_API_KEY` y `EMAIL_FROM` |
| **Gmail por SMTP** | Plan Starter de Render o en local | Verificación en dos pasos en la cuenta de Google y una *contraseña de aplicación*. Variables `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` |

Para que los correos no acaben en spam, lo ideal es un remitente de un dominio propio (por ejemplo `tpv@a2wd.es`)
autenticado en Brevo (registros DKIM en el DNS). Sin configurar nada, en local el enlace aparece en la consola del backend.

## 4. Nada más publicarlo

1. Entra con `admin@weedlemon.es` y tu contraseña.
2. *Socios y equipo* → cambia la contraseña del cajero (`cajero123` está en el repositorio, que es público).
3. Sube el PDF del acuerdo legal y prueba el alta por QR desde un móvil (la cámara necesita HTTPS, que Render pone).

## Variables de entorno

| Variable | Para qué | En Render |
|---|---|---|
| `MONGO_URL`, `DB_NAME` | Conexión a MongoDB | Obligatorias |
| `JWT_SECRET` | Firma de las sesiones; en producción el servidor **no arranca** si tiene menos de 32 caracteres | Generada |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Administrador que se crea en el primer arranque | Obligatorias |
| `FRONTEND_URL` | Dirección pública: CORS y enlaces de los correos | Obligatoria con correo |
| `FILE_STORAGE` | `mongo` (por defecto en el Dockerfile), `local` o `emergent` | No tocar |
| `COOKIE_SAMESITE` | `lax` por defecto en el Dockerfile (app y API en la misma web) | No tocar |
| `BREVO_API_KEY` | Envío de correos por la API de Brevo | Recomendada |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SECURITY` | Envío por SMTP (`SMTP_SECURITY`: `starttls`, `ssl` o `none`) | Solo en plan de pago |
| `EMAIL_FROM`, `EMAIL_FROM_NAME` | Remitente de los correos | Con el correo |
| `ADMIN_RESET_PASSWORD` | `true` solo para recuperar la contraseña del admin si no hay correo; quitar después | — |

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
