# Área administrativa: layout común y filtro Día/Mes

Rama: `style/admin-unified-period-filters`.

## Layout y navegación

`users/admin_base.html` centraliza HTML, dependencias, fondo, contenedor, acceso al contenido y navbar. Reutiliza `users/partials/branded_navbar.html` con `admin_nav=True`; no existe una segunda implementación de navegación.

Las cuatro secciones son Dashboard, Reservas, Canchas y Mi perfil. Cerrar sesión es un formulario POST separado con CSRF, al extremo derecho en desktop. En móvil/tablet hay un menú desplegable con estado accesible, Escape y recuperación de foco. El activo se deriva del resolver de Django; crear/detallar reservas marca Reservas, editar canchas/establecimientos marca Canchas, y cambiar contraseña marca Mi perfil. Se elimina el menú de cuenta duplicado dentro del navbar admin.

Reutilizan la base:

- Dashboard.
- Reservas, nueva reserva manual y detalle de reserva.
- Canchas, editar cancha y editar establecimiento.
- Perfil administrativo, cambio de contraseña y confirmación de cambio.

`account_base.html` selecciona la base según el rol; el usuario común conserva su navegación y layout de cuenta. Los catálogos públicos mantienen su navegación pública.

## CSS

`users/static/users/css/admin.css` contiene los componentes comunes extraídos del Dashboard: fondo, superficies, bordes, tipografía, navbar, inputs, botones, tablas, badges, alertas y responsive. Reutiliza `--brand-lime` y las variables existentes. Las hojas originales conservan solo lo específico: gráficos/KPIs, estructura de reservas, grillas/imágenes y carga de archivos, o autocomplete y resumen de la reserva manual. El Dashboard mantiene sus estilos de gráficos e indicadores.

Las tablas tienen scroll interno y los contenedores no fuerzan anchuras mínimas globales. Las cards de Canchas mantienen su estructura e información real; los estados Activa/Inactiva se muestran usando `is_active`.

## Día/Mes

El Dashboard acepta:

- `periodo=day&fecha=2026-10-27` → `fecha_inicio=fecha_fin=2026-10-27`.
- `periodo=month&mes=2026-10` → `fecha_inicio=2026-10-01`, `fecha_fin=2026-10-31`.

`DashboardFilterForm` usa `calendar.monthrange()` para determinar el último día, incluidos años bisiestos. El día actual de Bogotá es el valor predeterminado. El selector activo tiene fondo lima; solo el control temporal activo se muestra y envía.

El formulario elimina los tres campos de presentación de `cleaned_data` antes de devolver los filtros: los consumidores continúan recibiendo exactamente el contrato existente (origen, establecimiento, cancha, inicio, fin y tipo). KPIs, Chart.js, análisis de OpenAI y ownership no se modifican. Se comprueba que un mes histórico produce los mismos KPIs, gráficos y contrato de análisis que el rango explícito equivalente.

Las URLs antiguas con `fecha_inicio/fecha_fin`, sin `periodo`, continúan aceptándose. Al aplicar el nuevo formulario se usa Día o Mes. El POST del análisis sigue usando el rango canónico existente, sin añadir campos de UI al contrato.

Para permitir el mes actual completo, ambos tipos de análisis aceptan ese mes aunque cruce hoy. Se conservan los rechazos de meses enteramente futuros para histórico y meses enteramente pasados para programado, así como las restricciones previas de los rangos antiguos. Las reglas y cálculos históricos/programados de los servicios permanecen intactos.

## Validación

```sh
.venv/bin/python manage.py test --settings=config.test_settings
node --check users/static/users/js/admin.js
node --test tests/dashboard_insights.test.cjs
```

Cobertura añadida: día, mes, febrero bisiesto/no bisiesto, meses de 30/31 días, diciembre, entradas inválidas, mes actual en ambos análisis, zona horaria, compatibilidad de rangos, equivalencia de KPIs/gráficos/contrato y ownership. Se verifica el componente y sección activa de diez páginas administrativas y la separación del layout del usuario común.

Prueba de Chrome con una base aislada en 1440, 768 y 375 px: diez vistas, navbar móvil/desktop, logout, Escape, ausencia de scroll horizontal general, selección y envío Día/Mes, Chart.js y autocomplete de usuario. No se crean ni modifican reservas durante esta comprobación.

## Límites y deuda fuera del cambio visual

- El módulo propio de Canchas no tiene una vista de creación; solo listado y edición. No se agrega un botón «Nueva cancha» sin un flujo existente al cual dirigirlo. La creación disponible en Django Admin es un módulo técnico separado con permisos propios; incorporar esa función al layout del producto requiere definir su alcance funcional.
- Los rangos antiguos se siguen admitiendo por compatibilidad; el formulario nuevo los reemplaza por el modo Día/Mes al aplicarse.
- Bootstrap sigue cargándose desde el CDN existente; no se cambia la gestión global de dependencias estáticas.
- La prueba aislada usa SQLite y no modifica Neon ni sustituye comprobaciones de concurrencia en PostgreSQL.

## Archivos del cambio

Nuevos: `users/templates/users/admin_base.html`, `users/static/users/css/admin.css`, `users/static/users/js/admin.js`, `reservations/test_admin_period_layout.py` y este documento.

Modificados: `reservations/forms.py`; las plantillas administrativas `admin_dashboard.html`, `admin_reservas.html`, `admin_crear_reserva.html`, `admin_detalle_reserva.html`; `reservations/static/reservations/admin_dashboard.css` y `css/admin_reservas.css`; `courts/templates/courts/admin_canchas.html`, `admin_editar_cancha.html`, `admin_editar_establecimiento.html`; `courts/static/courts/css/admin_courts.css`; `users/templates/users/account_base.html`, `password_done.html`, `partials/branded_navbar.html`.

El cambio de salto de línea preexistente en `resumen_reserva.html` se conserva y no forma parte de esta implementación.
