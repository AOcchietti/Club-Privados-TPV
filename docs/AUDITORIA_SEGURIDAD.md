# Auditoría de seguridad y pruebas · TPV Weed Lemon

Rama `demo` · 31/10/2026

## Resumen

- **26 problemas encontrados y corregidos**: 5 de gravedad alta, 9 media y 12 baja. La tabla con todos está más abajo.
- **El más grave**: al quinto intento de contraseña fallido, el login daba un error interno, y lo seguía dando para siempre para esa persona desde esa conexión. Venía del código original.
- **Datos personales**: la aplicación enviaba grabaciones de pantalla a un servicio de analítica de Emergent, incluido el formulario de alta. Se ha eliminado.
- **Pruebas automáticas**: cuatro bloques en `backend/tests` que hacen **más de 3,8 millones de comprobaciones** y pasan todas. Se repiten con `python tests/run_all.py`.
- **Las propias pruebas están verificadas**: se metieron **20 errores a propósito** en copias del servidor y las pruebas detectaron los 20.
- **Servidor real**: GitHub repite las pruebas en cada push con FastAPI, bcrypt y **MongoDB 8 reales**, recorre la app por HTTP, arranca la imagen de despliegue, abre la app en un navegador y busca vulnerabilidades en las dependencias.

## Alcance y método

**Qué se ha revisado:**
- Backend completo: `server.py` y `cierre_pdf.py`, 52 rutas de la API.
- Partes del frontend relevantes para la seguridad: cliente de la API, `index.html`, gestión de sesión y subidas de archivos.

Cada riesgo se ha clasificado según la **tríada CIA**:

| | Pregunta | Ejemplos en el TPV |
|---|---|---|
| **C** · Confidencialidad | ¿Solo ve los datos quien debe? | DNI y fotos de socios, saldos, histórico de ventas |
| **I** · Integridad | ¿Nadie puede alterar datos de forma indebida y las cuentas siempre cuadran? | Stock, saldos, caja, recuentos, acuerdo legal |
| **A** · Disponibilidad | ¿El servicio sigue funcionando ante errores o abusos? | Login, formulario público, turnos |

## Clases de pruebas realizadas

1. **Revisión de código (análisis estático)**
   - Lectura de todas las rutas de la API.
   - Mapa automático de quién puede llamar a cada una, obtenido del propio código.
   - Búsqueda de patrones peligrosos: ejecución de código, consultas sin escapar, secretos escritos en el repositorio.
2. **Pruebas funcionales de punta a punta** (`test_flows.py`, 234 comprobaciones). Recorren los procesos reales en orden: productos, inventario, ventas y recargas con y sin turno, apertura, recuento, cierre, PDF (incluidos los umbrales de descuadre), catálogo de refrescos y dulces, cantidades enteras en productos por unidades, subcategorías, botón de rellenar todo el recuento, alta pública con QR, usuarios y migración de datos antiguos.
3. **Pruebas de seguridad por la tríada CIA** (`test_security.py`, 161 comprobaciones).
   - **Confidencialidad**:
     - Control de acceso de las 52 rutas.
     - Tokens manipulados: caducados, firmados con otra clave, de otro tipo, con algoritmo "none", con rol falsificado.
     - Cuentas suspendidas.
     - Datos que nunca deben salir: hashes de contraseñas, datos internos en el formulario público.
   - **Integridad**:
     - CSRF.
     - Subida de archivos maliciosos (SVG con script, HTML disfrazado de PNG).
     - Inyección en búsquedas y operadores de MongoDB.
     - Asignación masiva de campos protegidos (rol, saldo, nº de socio).
     - Precios y cantidades manipulados desde el cliente.
   - **Disponibilidad**:
     - Fuerza bruta en el login.
     - Suplantación de IP para saltarse los límites.
     - Inundación del formulario público.
     - Archivos enormes.
     - Búsquedas diseñadas para colgar el servidor (ReDoS).
     - Dos turnos abiertos a la vez.
4. **Pruebas de consistencia con simulación aleatoria** (`test_invariants.py`, unos 3,8 millones de comprobaciones).
   - Se simulan **7.500 operaciones al azar** en 5 escenarios distintos, como muchos días de trabajo en el club. Unos 170 turnos abiertos y cerrados, recuentos que no cuadran, cancelaciones, mermas, productos desactivados, ventas y recargas fuera de turno, y "ataques" a la consistencia.
   - **Después de cada operación** se comprueban 11 reglas que nunca pueden romperse:
     - Un solo turno activo.
     - Nunca stock negativo.
     - El libro de stock y el de saldos cuadran al céntimo.
     - Cada venta o recarga pertenece a un turno válido.
     - La caja de cada turno cuadra con sus movimientos.
     - Tickets y números de socio únicos.
     - Los recuentos finales están completos.
     - Lo disponible nunca es negativo.
     - El efectivo esperado nunca es negativo.
     - Los productos por unidades (latas, chocolatinas…) nunca tienen stock ni ventas con decimales.
5. **Pruebas de mutación** (`test_mutations.py`). Comprueban que las pruebas sirven:
   - Se introducen 20 errores típicos en copias del servidor. Por ejemplo: "la venta no descuenta el saldo", "sin protección CSRF", "se aceptan SVG" o "el PDF trata igual los productos caros y los baratos".
   - Las pruebas deben fallar con cada uno, y detectaron **20 de 20**.
   - Gracias a esto se encontró y cerró un hueco de las propias pruebas: no comprobaban mermas que se comieran stock ya vendido fuera de turno.
6. **Pruebas de interfaz**:
   - Compilación completa del frontend.
   - Renderizado real en un navegador (Chromium) del TPV y de Caja con datos de prueba, para verificar el diseño y que los productos sin stock desaparecen.
   - Generación y revisión visual del PDF de cierre en casos normal, vacío y extremo (60 movimientos, 120 diferencias): siempre cabe en una página.

7. **Pruebas contra el servidor real** (GitHub Actions, `.github/workflows/pruebas.yml`, en cada push):
   - Las cuatro baterías anteriores con los paquetes reales instalados.
   - `tests/e2e_real.py`: recorrido completo por HTTP contra FastAPI + MongoDB 8. Comprueba CSRF, cookies `httpOnly`, el bloqueo de intentos (el fallo n.º 1 solo aparecía con MongoDB real), el cierre de sesión, las subidas, las subcategorías, los turnos, 12 ventas simultáneas de 5 latas y el PDF. Después se reinicia el servidor y se comprueba que no se duplica ni se pierde nada.
   - La imagen Docker de despliegue en modo producción: la app y la API salen del mismo servidor, un contenedor nuevo conserva las fotos (guardadas en MongoDB) y un navegador real (Chromium) entra, vende, abre Caja y Gestión sin pedir nada a terceros.
   - `pip-audit` (backend) y `npm audit` de lo que llega al navegador.

## Hallazgos y correcciones

| # | Problema encontrado | CIA | Gravedad | Estado |
|---|---|---|---|---|
| 1 | Tras 5 intentos fallidos el login daba un **error interno para siempre** a esa persona desde esa conexión: no podía volver a entrar. Venía del código original: comparaba fechas con y sin zona horaria. | A | Alta | Corregido y con prueba |
| 2 | `index.html` cargaba **PostHog con grabación de sesiones** y otro script de Emergent: lo que aparecía en pantalla (nombres, documentos, saldos, formulario de alta) se enviaba a un tercero. | C | Alta | Corregido (eliminados) |
| 3 | **CSRF**: en producción las cookies van con `SameSite=None`. Otra web podía hacer peticiones con la sesión de un administrador, por ejemplo cambiar el acuerdo legal o iniciar el cierre de caja. | I | Alta | Corregido: cabecera `X-Requested-With` obligatoria |
| 4 | Se aceptaba cualquier `image/*`, también **SVG con JavaScript** (XSS almacenado al abrir el archivo). | I · C | Alta | Corregido: solo JPG/PNG/WEBP/GIF verificados por su contenido |
| 5 | Dos ventas simultáneas podían llevarse el mismo stock y dejarlo en **negativo** (carrera de lectura y escritura). | I | Media | Corregido: descuento atómico con marcha atrás |
| 6 | Una merma sin turno podía dar de baja stock **ya vendido fuera de turno**, y al abrir el siguiente turno el stock quedaba negativo. | I | Media | Corregido |
| 7 | Una cuenta **suspendida seguía entrando** con su sesión hasta 8 horas. | C | Media | Corregido: se comprueba en cada petición |
| 8 | **Credenciales por defecto**: la contraseña del admin se reescribía con `admin123` en cada arranque, y el cajero de ejemplo reaparecía aunque se borrara. | C | Media | Corregido: datos de ejemplo solo en el primer arranque |
| 9 | Los límites de intentos usaban la IP que **escribe el propio cliente** en `X-Forwarded-For`: se podían saltar. | A | Media | Corregido |
| 10 | La búsqueda de productos usaba el texto como **expresión regular**: un patrón trampa podía bloquear la base de datos (ReDoS). | A | Media | Corregido |
| 11 | Las subidas se leían enteras en memoria antes de comprobar su tamaño. | A | Baja | Corregido |
| 12 | Un cajero podía descargar **todo el histórico de ventas** llamando directamente a la API. | C | Baja | Corregido: solo las de un socio concreto |
| 13 | El login devolvía el token también en el cuerpo de la respuesta, al alcance de JavaScript. | C | Baja | Corregido: solo en la cookie `httpOnly` |
| 14 | Se podía **borrar un socio con saldo o deuda**, y se perdía el rastro contable. | I | Baja | Corregido: hay que dejarlo a 0 o suspenderlo |
| 15 | Contraseñas del equipo sin longitud mínima. | C | Baja | Corregido: mínimo 8 |
| 16 | Faltaban cabeceras de seguridad (nosniff, anti-iframe, referrer). | C · I | Baja | Corregido |
| 17 | CORS admitía `localhost:3000` también en producción. | C | Baja | Corregido |
| 18 | Se aceptaban cantidades absurdas en recuentos y movimientos de stock. | I | Baja | Corregido: límite de cordura |
| 19 | Se podía vender o contar media lata en productos por unidades. | I | Baja | Corregido: solo enteros |
| 20 | **Dependencias con vulnerabilidades conocidas**: Starlette 0.37 (fijada por FastAPI 0.110.1), python-multipart, PyJWT 2.10.1, requests; en el navegador, axios 1.18.0, react-router 7.15.0 y zod 3.24.4 (que ni se usaba). | C · I · A | Alta | Corregido: versiones parcheadas, zod fuera y vigilancia en cada push |
| 21 | Al **cerrar sesión**, una copia de la cookie seguía valiendo hasta 8 horas. | C | Media | Corregido: los tokens se anulan en el servidor |
| 22 | En producción el servidor arrancaba con un `JWT_SECRET` corto (solo avisaba): con una clave débil se pueden falsificar sesiones. | C · I | Media | Corregido: no arranca |
| 23 | Las fotos de DNI y el acuerdo legal se guardaban en el disco del servidor: en un hosting sin disco permanente se perderían en cada reinicio. | A · I | Media | Corregido: opción de guardarlos en MongoDB (`FILE_STORAGE=mongo`) |
| 24 | Con bcrypt 5, una contraseña de más de 72 bytes daba error interno al crearla. | A | Baja | Corregido: se rechaza con un mensaje; las guardadas siguen valiendo |
| 25 | Las tipografías se cargaban de **Google Fonts**: Google recibía la IP de quien abría el TPV o el formulario de alta. | C | Baja | Corregido: alojadas en la propia app |
| 26 | Cada instalación del frontend descargaba paquetes de `assets.emergent.sh` (herramientas de la preview). | I | Baja | Corregido: eliminados |

### Lo que ya estaba bien

- Las contraseñas se guardan con **bcrypt**.
- Los permisos se comprueban en el servidor, no solo ocultando botones.
- El rol de cada persona se lee de la base de datos, no del token, así que no se puede falsificar.
- Los precios los pone siempre el servidor.
- Los datos se validan por tipo.
- Hay **registro de actividad** de todas las operaciones.
- Un único turno activo, garantizado por la base de datos.
- Los recuentos tienen control de versiones, por si se cuenta desde dos dispositivos a la vez.

## Recomendaciones de la primera auditoría: estado

| Recomendación | Estado |
|---|---|
| Actualizar dependencias y pasar `pip-audit` / `npm audit` | Hecho (n.º 20). GitHub los repite en cada push |
| Producción: HTTPS, `JWT_SECRET` fuerte, contraseña propia del admin | HTTPS lo pone Render; el servidor no arranca con clave corta y avisa si el admin usa la de ejemplo. Falta poner tus contraseñas al desplegar (`docs/DESPLIEGUE.md`) |
| Cierre de sesión que anule el token | Hecho (n.º 21) |
| Google Fonts | Hecho (n.º 25) |
| Probar con el servidor y MongoDB reales | Hecho: GitHub Actions con MongoDB 8, Docker y navegador |
| RGPD: copias cifradas, plazo de conservación de las fotos | Fuera del código: activar las copias de Atlas y decidir el plazo |

Pendiente de mantenimiento (no urgente): Motor, el driver de MongoDB, está en desuso desde 2025 y deja de tener soporte el 14/05/2027 (cambiar a la API asíncrona de PyMongo); Create React App no tiene mantenimiento (pasar a Vite). Los avisos que quedan en `npm audit` completo son de sus herramientas de compilación, que no llegan al navegador.

## Cómo repetir las pruebas

```bash
cd backend
python tests/run_all.py
```

No necesita MongoDB ni el servidor arrancado. Tarda unos 40 segundos.

Contra un servidor real (escribe datos: solo con una base de datos de pruebas):

```bash
python tests/e2e_real.py http://localhost:8001 --si
```
