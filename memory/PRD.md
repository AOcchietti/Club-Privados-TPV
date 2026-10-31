# PRD — Weed Lemon Social Club · Sistema de Ventas (TPV)

## Problem statement original
"haz una aplicacion para este club social: Weed Lemon Social Club (Club de cannabis, Demetrio de los Ríos 5, Sevilla)"
Decisiones del usuario: sistema de ventas con venta de productos, creación/modificación/estado, consulta de usuarios, histórico de todo, caja; panel admin para productos y usuarios con distintos roles; diseño moderno, simple, intuitivo, colorido con tonos suaves, alegres y tranquilos.

## Arquitectura
- Backend: FastAPI + MongoDB (motor) en /app/backend/server.py. Auth JWT (bcrypt + cookies httpOnly + Bearer). Roles: admin, cajero, socio.
- Frontend: React + Tailwind + Shadcn UI + framer-motion + sonner + recharts. Estética "Lemon-Herbal Botanical Calm" (amarillo limón #EAB308, verde salvia #10B981, crema andaluz). Tipografías Outfit + Manrope.
- Colecciones: users, products, sales, cash_sessions, cash_movements, activity, login_attempts, counters.

## Personas
- Admin: gestiona productos, equipo, socios, caja y auditoría.
- Cajero: vende en el TPV, da de alta socios, maneja la caja de su turno.
- Socio: no hace login; es cliente dispensario identificado por nº de socio (WL-XXXX).

## Implementado (21/09/2026)
- Login con roles, bloqueo anti fuerza bruta, seed idempotente de admin/cajero/productos/socios.
- TPV: catálogo con búsqueda y filtros por categoría, carrito con cantidades en gramos/unidades, asignación de socio, pago efectivo/tarjeta, ticket imprimible con numeración correlativa, descuento automático de stock.
- Productos: CRUD completo (admin), activar/desactivar, THC/CBD, stock, precios por gramo/unidad.
- Socios y equipo: alta, edición, baja, estados (activa/expirada/suspendida), roles admin/cajero; el cajero solo gestiona socios.
- Caja: apertura/cierre de turno con fondo, entradas/salidas manuales con motivo, arqueo con esperado/contado/diferencia, historial de turnos.
- Histórico de ventas: filtros por periodo y método de pago, vista de ticket.
- Actividad: auditoría de todas las operaciones (solo admin).
- Panel: métricas del día, gráfico de ventas 7 días, top productos, alertas de stock bajo.

## Implementado (21/09/2026, iteración 2)
- Página inicial = stock de productos, con selector de vista Fotos (cuadrícula grande con imágenes reales) / Lista.
- Fotos de producto: campo image_url en productos (editable en el diálogo), fotos reales sincronizadas para las 10 referencias.
- Saldo de socios: recarga (efectivo/tarjeta, importes rápidos), histórico de recargas, pago "saldo" en el TPV con validación de saldo insuficiente y descuento automático. Las recargas en efectivo/tarjeta se suman al arqueo de caja.
- Ficha completa del socio (/socios/:id): datos, saldo, stats (compras, gastado, gramos, recargado), histórico de compras con tickets y de recargas; acciones Recargar y Vender.
- Acciones rápidas en la tabla de socios: ver ficha, recargar saldo y vender (lleva al TPV con el socio ya asignado vía /tpv?socio=ID).
- TPV: preasignación de socio por URL, chip de socio con saldo visible y botón Recargar inline, método de pago "saldo".

## Implementado (21/09/2026, iteración 3)
- Unidad de pago = créditos en toda la interfaz (precios, tickets, caja, saldos).
- Pestaña Gestión (/gestion) para todo el equipo: CRUD de productos con subida de fotos propias (object storage Emergent, /api/upload + /api/files con auth por cookie) o URL, y CRUD de categorías con colores (colección categories, seed de 5 por defecto, borrado bloqueado si hay productos usándola).
- Stock (/) ahora es solo catálogo de visualización: fotos/lista, búsqueda y filtros por categoría dinámicos.
- Permisos: productos y categorías = admin+cajero; Panel, Caja, Histórico y Actividad = solo admin (nav oculta, guard AdminOnly en rutas y 403 en backend). El cajero conserva TPV, socios y consulta de caja actual.
- TPV: dispensa por gramos o por créditos — chips rápidos +5/+10/+20 cr en productos por gramo con conversión visible (10 créditos ≈ X g), y en el carrito cada línea en gramos puede alternar modo "por gramos / por créditos" mostrando la equivalencia.

## Implementado (21/09/2026, iteración 4)
- Unidad de pago renombrada a "Cr" en toda la interfaz.
- Carrito del TPV con entrada numérica manual (además de los botones +/-): se puede escribir cualquier cantidad desde 0 en gramos o en Cr según el modo de la línea, con tope de stock automático. El campo se puede borrar por completo mientras se edita (borrador local); al salir vacío o en 0 la línea se elimina.
- Vista Fotos/Lista también en Gestión de productos (cuadrícula con fotos grandes y acciones de editar/activar/eliminar).
- Cobro únicamente desde el saldo del socio: el TPV exige asignar socio, muestra "saldo tras la compra" (rojo si queda en negativo) y permite deuda. El saldo negativo se refleja en la ficha del socio (tarjeta roja "Deuda pendiente"), en el registro de actividad (marca DEUDA con saldo resultante) y en Caja (tarjeta "Deuda de socios" + "Ventas con saldo" + "Recargas del turno"). Histórico simplificado: todas las ventas son con saldo.

## Implementado (05/10/2026, iteración 5 — versión de Emergent portada a GitHub)
Frontend copiado tal cual de la preview de Emergent; backend reconstruido a partir de las llamadas del frontend.
- Caja por turnos (uno activo por local, índice único `active_lock`): estados opening → open → closing → closed. Cajeros y admin pueden abrir; solo el responsable del turno o un admin lo operan; cancelar apertura/cierre es solo admin y queda auditado.
- Recuento de stock por secciones (categorías) al abrir y al cerrar (colección `stocktakes`, control de versión optimista, autorrelleno por sección o producto). Las diferencias se registran pero no ajustan el stock del sistema. Cierre en 3 pasos: arqueo de efectivo → recuento → revisión. Informe de turno (`GET /cash/sessions/{id}`).
- Ventas fuera de turno: sin turno abierto se puede vender; el saldo se descuenta al momento y el stock queda reservado hasta la siguiente apertura, que las incorpora y descuenta su stock antes del recuento. Durante apertura/cierre se pausan ventas, recargas y ajustes de stock.
- Inventario: el stock ya no se edita en la ficha; entradas, mermas y ajustes con motivo obligatorio (`POST /products/{id}/stock`, historial en `stock_movements`). Alta de producto con stock inicial; la unidad no cambia tras el alta.
- Recargas solo en efectivo y solo con turno abierto; entran en el arqueo.
- Equipo con nº de socio y saldo propios (pueden recargar y comprar). Migración automática al arrancar (nº de socio para todos, `dni` → `doc_type` + `doc_number`).
- Alta pública con QR (`/alta`, sin login): datos, foto del documento, foto facial, firma y aceptación del acuerdo legal (PDF subido por admin). Exige mayoría de edad y documento no repetido; el socio queda "pendiente" y no se le puede dispensar hasta activarlo. Subidas públicas y altas limitadas por IP.
- Nuevas dependencias backend: `segno` (QR).

## Implementado (05/10/2026, iteración 6)
- El recuento manda: al confirmar la apertura y al cerrar el turno, lo contado pasa a ser el stock del sistema (movimiento de stock tipo `recuento`). Si se marca "contado = esperado", el stock no cambia.
- Orden de secciones del recuento por palabras clave de la categoría (válido para cualquier club): flor/marihuana → hash/hachís → extracto → dry → polen → resto alfabético.
- TPV: sin stock visible ni botones rápidos +5/+10/+20 Cr; tarjetas cuadradas (imagen + nombre + precio) en rejilla adaptable. Barra lateral de 192 px (w-48) y ticket de 320 px, con cada línea del ticket en dos filas (nombre arriba, modo y cantidad abajo).
- Catálogo (Productos): solo productos activos, sin stock ni etiquetas de estado.
- Gestión: filtros por categoría, inactivos siempre al final y atenuados (sin etiqueta "Activo"); el motivo es opcional en las entradas de stock (sigue siendo obligatorio en mermas y ajustes). El stock sigue visible aquí.
- PDF con el resumen del cierre (`GET /cash/sessions/{id}/report.pdf`, admin o responsable del turno): turno, arqueo, ventas, productos vendidos, movimientos de caja y diferencias de los recuentos. Se descarga con un enlace directo: aviso con botón al cerrar el turno, icono en cada fila del histórico y botón en el informe del turno. Generado sin dependencias (`backend/cierre_pdf.py`).

## Implementado (31/10/2026, iteración 7 · rama `demo`)
- Recargas también sin turno abierto: el saldo sube al momento y el efectivo se incorpora al esperado del siguiente turno (como las ventas fuera de turno). Avisos en Caja y en el diálogo de recarga; aparecen en el informe y en el PDF del turno que las incorpora. Durante la apertura y el cierre siguen en pausa.
- PDF de cierre en una sola página A4 y sin la lista de productos vendidos; si hay muchos movimientos o diferencias, lista los primeros y añade "y N más".
- El TPV oculta automáticamente los productos sin stock disponible (stock menos lo vendido fuera de turno pendiente, campo `available`).
- Auditoría de seguridad (tríada CIA) con 18 correcciones: ver `docs/AUDITORIA_SEGURIDAD.md`. Destacan el fallo permanente del login tras 5 intentos, la protección CSRF (cabecera `X-Requested-With` obligatoria), solo imágenes reales en las subidas, la eliminación de la analítica de Emergent con grabación de sesiones, las ventas atómicas, la protección del stock vendido fuera de turno y los datos de ejemplo solo en el primer arranque.
- Batería de pruebas en `backend/tests` (`python tests/run_all.py`): funcionales, seguridad, invariantes con simulación aleatoria y mutación.

## Implementado (31/10/2026, iteración 8 · rama `demo`)
- PDF de cierre: en productos por gramos solo salen los descuadres de 1 g o más si el producto cuesta menos de 15 Cr/g, y de 0,5 g o más si cuesta 15 Cr/g o más (15 cuenta como caro). En productos por unidades sale cualquier diferencia. El PDF dice cuántas diferencias pequeñas no muestra y explica el criterio al pie. El recuento guarda el precio de cada producto; los recuentos antiguos usan el precio actual.
- Catálogo de comida y bebida: categorías "Refrescos" (Coca-Cola, Coca-Cola Zero, Fanta Naranja y Limón, Sprite, Aquarius, Nestea, agua) y "Dulces y snacks" (Kinder Bueno, Bueno White, Country, Delice, Twix, Snickers, KitKat, Chupa Chups), por unidades y con ilustraciones propias sin logotipos (`backend/demo_catalog.py`). Se añaden una sola vez al arrancar, también en bases ya existentes (marca `catalog_food_drinks_v1` en `settings`): lo que se borre o cambie después no se vuelve a crear.
- Productos por unidades: solo cantidades enteras en ventas, entradas/mermas/ajustes, stock inicial y recuentos (el TPV redondea hacia abajo y el botón + ya no pasa del stock disponible).

## Implementado (31/10/2026, iteración 9 · rama `demo`)
- Subcategorías opcionales (un solo nivel): en el mismo diálogo de "Nueva categoría" se marca "Es una subcategoría" y se elige "Dentro de". Una subcategoría puede llamarse igual que otra categoría (clave `madre-nombre`). No se puede borrar una categoría con subcategorías ni meter dentro de otra una categoría que ya las tiene. En Gestión cada categoría muestra sus subcategorías dentro de su tarjeta y el selector de producto muestra "Madre › Sub".
- Filtros con subcategorías en TPV, Productos y Gestión (`components/CategoryFilter.jsx`): al elegir una categoría que las tenga aparece debajo una segunda fila ("Todo X" + subcategorías). Elegir la madre incluye los productos de sus subcategorías (también en `GET /products?category=`).
- Orden único de categorías y productos (TPV, catálogo, gestión y recuento), calculado en el backend (`ordered_categories`): flor/marihuana → hash/hachís → extracto → dry → polen → resto alfabético; cada madre seguida de sus subcategorías.
- Recuento: una sección por categoría madre, con la subcategoría indicada en cada producto. Botón "Contado = esperado en todo el stock" en apertura y cierre (`autofill` con `all`); si ya hay productos contados con diferencia, pregunta si rellenar solo lo pendiente (`only_pending`) o todo.

## Implementado (31/10/2026, iteración 10 · rama `demo` · cierre de la auditoría y despliegue)
- Dependencias: `backend/requirements.txt` limpio (solo lo que usa el código) con mínimos sin vulnerabilidades conocidas (Starlette ≥ 1.0.1, python-multipart ≥ 0.0.31, PyJWT ≥ 2.12, requests ≥ 2.32.4). Frontend: axios ≥ 1.20, react-router ≥ 7.18; fuera zod y @hookform/resolvers (sin usar) y los paquetes de Emergent; react-scripts como devDependency.
- Compatibilidad con Starlette 1.x (`lifespan` en vez de `on_event`) y con bcrypt 5 (recorte a 72 bytes; contraseñas más largas se rechazan).
- Cerrar sesión anula en el servidor los tokens de ese dispositivo (`revoked_tokens` con TTL). En producción el servidor no arranca con un `JWT_SECRET` de menos de 32 caracteres.
- `FILE_STORAGE=mongo`: fotos y PDF dentro de MongoDB (`file_blobs`). El backend sirve el frontend compilado si existe (`frontend/build`): app y API en la misma web. `COOKIE_SAMESITE` configurable.
- Tipografías alojadas en la app (`@fontsource`), sin Google Fonts.
- Despliegue: `Dockerfile` (un solo servicio), `render.yaml`, guía `docs/DESPLIEGUE.md`.
- GitHub Actions (`.github/workflows/pruebas.yml`) con MongoDB 8 real: pruebas internas, `tests/e2e_real.py` por HTTP antes y después de reiniciar, imagen Docker en modo producción con contenedor nuevo, navegador real (`tests/ui_smoke.py`), `pip-audit` y `npm audit`.

## Backlog priorizado
- P0: nada bloqueante pendiente.
- P1: impresión/exportación de tickets y cierres (PDF/Z-report); límites de dispensación por socio/día (normativa CSC); caducidad de membresía con avisos; vista de socios con deuda (filtro en lista de socios).
- P2: modo táctil/tablet fullscreen; notificaciones de stock por email; precios por tramos.

## Próximas tareas
1. Límites legales de dispensación por socio (p. ej. 5 g/día) con alerta en el TPV.
2. Exportar cierre de caja y histórico a PDF/CSV.
3. Fotos de producto en el catálogo del TPV.
