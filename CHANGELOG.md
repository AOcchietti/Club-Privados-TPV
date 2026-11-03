# Historial de versiones

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones según
[Versionado Semántico](https://semver.org/lang/es/): `MAYOR.MENOR.PARCHE`. El detalle de cada iteración está en
[`memory/PRD.md`](memory/PRD.md) y la auditoría en [`docs/AUDITORIA_SEGURIDAD.md`](docs/AUDITORIA_SEGURIDAD.md).

## [Sin publicar]

Cambios en curso para la próxima versión.

## [1.0.0] · 2026-11-03

Primera versión estable: la que se presenta en la demo.

### Añadido
- **TPV** con cobro desde el saldo del socio, ventas por gramos o por Cr, ticket y numeración correlativa.
- **Caja por turnos** (apertura → turno → cierre) con recuento de stock por secciones, arqueo, informe y **PDF de cierre** en una página.
- Ventas y recargas **fuera de turno**, que se incorporan a la siguiente apertura.
- **Inventario** con entradas, mermas y ajustes con historial; el recuento pasa a ser el stock del sistema.
- **Categorías con subcategorías** opcionales, filtros en dos niveles y orden flor → hash → extracto → dry → polen → resto.
- Botón **«Contado = esperado en todo el stock»** en apertura y cierre.
- Catálogo de **refrescos y dulces** de ejemplo con ilustraciones propias.
- **Alta pública de socios con QR**: documento, foto, firma y acuerdo legal.
- **Recuperación de contraseña por email**: enlace de un solo uso que caduca en 30 minutos, aviso de cambio y cierre de las
  sesiones abiertas. Correo por Brevo (API HTTPS) o SMTP.
- **Despliegue**: `Dockerfile` (app y API en un solo servicio), `render.yaml` y guía en `docs/DESPLIEGUE.md`.
- **Pruebas en GitHub** en cada push con MongoDB 8 real: funcionales, seguridad, invariantes, mutación, recorrido por HTTP,
  imagen de despliegue, navegador real, correo con Mailpit, `pip-audit` y `npm audit`.

### Seguridad
- 27 fallos corregidos en la auditoría (tríada CIA), entre ellos: login bloqueado para siempre tras 5 intentos, analítica de
  terceros con grabación de pantalla, CSRF, subida de SVG con script, ventas simultáneas que dejaban stock negativo y
  `/auth/me` roto (la sesión se perdía al recargar).
- Dependencias sin vulnerabilidades conocidas (Starlette 1.x, PyJWT, python-multipart, axios, react-router…).
- Cerrar sesión anula el token; en producción no se arranca con una clave de sesiones débil; tipografías sin Google Fonts.

### Cambiado
- Unidad de pago: **Cr**. Recargas en efectivo, también sin turno abierto.
- Productos por unidades: solo cantidades enteras.
- Descuadres del PDF: en gramos desde 1 g (menos de 15 Cr/g) o desde 0,5 g (15 Cr/g o más).

[Sin publicar]: https://github.com/AOcchietti/Club-Privados-TPV/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/AOcchietti/Club-Privados-TPV/releases/tag/v1.0.0
