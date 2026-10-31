# Auditoría de seguridad y pruebas · TPV Weed Lemon

Rama `demo` · 31/10/2026

## Resumen

- **18 problemas encontrados y corregidos**: 4 de gravedad alta, 6 media y 8 baja. La tabla con todos está más abajo.
- **El más grave**: al quinto intento de contraseña fallido, el login daba un error interno, y lo seguía dando para siempre para esa persona desde esa conexión. Venía del código original.
- **Datos personales**: la aplicación enviaba grabaciones de pantalla a un servicio de analítica de Emergent, incluido el formulario de alta. Se ha eliminado.
- **Pruebas automáticas**: cuatro bloques en `backend/tests` que hacen **más de 3,8 millones de comprobaciones** y pasan todas. Se repiten con `python tests/run_all.py`.
- **Las propias pruebas están verificadas**: se metieron **16 errores a propósito** en copias del servidor y las pruebas detectaron los 16.

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
2. **Pruebas funcionales de punta a punta** (`test_flows.py`, 198 comprobaciones). Recorren los procesos reales en orden: productos, inventario, ventas y recargas con y sin turno, apertura, recuento, cierre, PDF (incluidos los umbrales de descuadre), catálogo de refrescos y dulces, cantidades enteras en productos por unidades, alta pública con QR, usuarios y migración de datos antiguos.
3. **Pruebas de seguridad por la tríada CIA** (`test_security.py`, 145 comprobaciones).
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
   - Se introducen 16 errores típicos en copias del servidor. Por ejemplo: "la venta no descuenta el saldo", "sin protección CSRF", "se aceptan SVG" o "el PDF trata igual los productos caros y los baratos".
   - Las pruebas deben fallar con cada uno, y detectaron **16 de 16**.
   - Gracias a esto se encontró y cerró un hueco de las propias pruebas: no comprobaban mermas que se comieran stock ya vendido fuera de turno.
6. **Pruebas de interfaz**:
   - Compilación completa del frontend.
   - Renderizado real en un navegador (Chromium) del TPV y de Caja con datos de prueba, para verificar el diseño y que los productos sin stock desaparecen.
   - Generación y revisión visual del PDF de cierre en casos normal, vacío y extremo (60 movimientos, 120 diferencias): siempre cabe en una página.

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

### Lo que ya estaba bien

- Las contraseñas se guardan con **bcrypt**.
- Los permisos se comprueban en el servidor, no solo ocultando botones.
- El rol de cada persona se lee de la base de datos, no del token, así que no se puede falsificar.
- Los precios los pone siempre el servidor.
- Los datos se validan por tipo.
- Hay **registro de actividad** de todas las operaciones.
- Un único turno activo, garantizado por la base de datos.
- Los recuentos tienen control de versiones, por si se cuenta desde dos dispositivos a la vez.

## Recomendaciones pendientes

Estas no se han podido hacer o comprobar desde aquí:

1. **Dependencias**:
   - `requirements.txt` (el entorno de Emergent) fija `fastapi==0.110.1`. Esa versión arrastra Starlette ≤ 0.37, con vulnerabilidades conocidas en el procesado de formularios (por ejemplo CVE-2024-47874, denegación de servicio). Conviene actualizarla.
   - `requirements-local.txt` ya instala versiones actuales.
   - No se pudo ejecutar `pip-audit` ni `npm audit`, porque no había acceso a los registros de paquetes.
2. **Producción**:
   - HTTPS obligatorio, y no poner `COOKIE_SECURE=false`.
   - `JWT_SECRET` aleatorio de más de 32 caracteres. El servidor avisa si es corto.
   - Contraseña de administrador propia, y cambiar o borrar los usuarios de ejemplo de la demo.
3. **Datos personales (RGPD)**:
   - Las fotos de DNI y caras son datos sensibles: copias de seguridad cifradas de MongoDB y del almacenamiento de archivos.
   - Política de cuánto tiempo se guardan.
   - Acceso solo para el equipo, que ya es así.
4. **Cierre de sesión**: borra la cookie, pero un token copiado seguiría siendo válido hasta 8 horas. Está mitigado porque el token no es accesible desde JavaScript. Si se quiere más, una lista de tokens revocados o sesiones más cortas.
5. **Google Fonts**: las tipografías se descargan de Google, que recibe la IP de quien abre la app. Se pueden alojar en el propio servidor.
6. **Límites de las pruebas**:
   - Las pruebas automáticas llaman a las funciones del backend directamente, sin HTTP real y con una base de datos en memoria que imita a MongoDB.
   - Antes de usarlo en el club, conviene una pasada manual con el servidor y MongoDB reales.

## Cómo repetir las pruebas

```bash
cd backend
python tests/run_all.py
```

No necesita MongoDB ni el servidor arrancado. Tarda unos 20 segundos.
