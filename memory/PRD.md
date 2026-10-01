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

## Backlog priorizado
- P0: nada bloqueante pendiente.
- P1: impresión/exportación de tickets y cierres (PDF/Z-report); límites de dispensación por socio/día (normativa CSC); caducidad de membresía con avisos; vista de socios con deuda (filtro en lista de socios).
- P2: modo táctil/tablet fullscreen; notificaciones de stock por email; precios por tramos.

## Próximas tareas
1. Límites legales de dispensación por socio (p. ej. 5 g/día) con alerta en el TPV.
2. Exportar cierre de caja y histórico a PDF/CSV.
3. Fotos de producto en el catálogo del TPV.
