# PLAN — EventContractLinterPlugin (linter de contratos de eventos)

> Plan de implementación. Objetivo: detectar en boot que los payloads publicados en el
> bus son compatibles con lo que los consumidores esperan, al estilo del
> `ArchitectureLinterPlugin` existente (mismo patrón: escaneo AST en `on_boot`,
> warnings al logger, findings a `registry.register_domain_metadata`).

## Ubicación y patrón

- `domains/devtools/plugins/event_contract_linter_plugin.py` (1 archivo = 1 feature).
- DI: `def __init__(self, container, logger, registry, http)` — mismo acceso que el arch linter (`container.registry`), más `http` para el endpoint de exposición.
- Corre en `on_boot()`: escanea `domains/*/plugins/*.py` con `ast`, cruza publishers vs consumers, registra findings. Cero coste en runtime (v1 es 100% estático).

## Fase 1 — Extracción estática (AST)

### Publishers
Buscar llamadas `*.publish(<evento>, <payload>, ...)`:
- Evento como literal `str` → registrar. Evento dinámico (variable, f-string) → finding informativo `DYNAMIC_EVENT` (no verificable) y seguir.
- Payload como dict literal → extraer claves literales. Si el dict tiene `**spread` → claves conocidas + flag `open=True` (se suprime el check de claves faltantes para ese sitio, no es error).
- Payload como variable/llamada → intentar resolver hacia atrás SOLO el caso trivial (asignación previa de dict literal en la misma función); si no, `UNKNOWN_PAYLOAD` informativo.
- Registrar sitio: `dominio`, archivo, línea, clase plugin.

### Consumers
Buscar `*.subscribe(<evento>, self.<handler>, ...)` con evento literal → localizar el `FunctionDef`/`AsyncFunctionDef` del handler en la misma clase (AST del mismo archivo; la regla "no cross-domain imports" garantiza que el handler vive ahí). Dentro del cuerpo del handler, con el nombre del parámetro evento (típicamente `event`):
- `event.payload["k"]` (Subscript) → clave **requerida**.
- `event.payload.get("k")` → clave **opcional** (no genera error si falta).
- `event.payload.get("k", default)` → opcional.
- Alias `p = event.payload` → seguir el alias dentro de la misma función (solo asignación directa, sin flujo complejo).
- Acceso no analizable (pasa `event.payload` entero a otra función, iteración dinámica) → marcar consumer como `OPAQUE_CONSUMER` (informativo, sin errores de claves).

También considerar `request(<evento>, ...)` como publisher (mismo análisis de payload).

## Fase 1 — Chequeos y severidades

Por cada evento con al menos un publisher y un consumer analizables:

| Código | Condición | Severidad |
|---|---|---|
| `MISSING_KEY` | Un consumer requiere (Subscript) una clave que algún sitio de publicación no incluye (y ese sitio no es `open`) | **warning** (el objetivo central) |
| `ORPHAN_PUBLISH` | Evento publicado sin ningún subscriber estático | info |
| `ORPHAN_SUBSCRIBE` | Subscriber de un evento que nadie publica | info |
| `UNKNOWN_PAYLOAD` / `DYNAMIC_EVENT` / `OPAQUE_CONSUMER` | No verificable estáticamente | info |

Excluir siempre `_dlq.*`, `_reply.*` y wildcards. Los eventos del propio dominio `system` (`system.one_shot.*`, `event.delivery.failed`) se analizan igual — sin casos especiales.

Formato de finding (dict serializable):
```python
{"code": "MISSING_KEY", "severity": "warning", "event": "user.created",
 "publisher": "users.CreateUserPlugin (create_user_plugin.py:57)",
 "consumer": "users.WelcomeServicePlugin.on_user_created",
 "detail": "consumer requiere 'email' pero el publish de la línea 57 no la incluye"}
```

Salida en `on_boot`:
- `self.registry.register_domain_metadata("system", "event_contract_violations", findings)`
- `logger.warning` por cada warning, `logger.info` resumen de infos (no spamear).

## Fase 1b — Endpoint `GET /system/lint`

Nuevo endpoint (puede ir en este mismo plugin) que devuelva las tres fuentes de lint desde `registry.get_domain_metadata()`:
```json
{"success": true, "data": {"arch_violations": [...], "drift_warnings": [...], "event_contract_violations": [...]}}
```
Con `response_model` Pydantic como exige el manifiesto. Este endpoint lo consume MicroCoreMap (ver `../../PLAN_MICROCOREMAP.md`, overlay de linters).

## Fase 2 (opcional, decidir después de usar la Fase 1) — Validación en runtime

Sink `event_bus.add_listener(...)` que valida cada payload real contra los requisitos inferidos de sus consumers y acumula discrepancias (contador + último ejemplo) en memoria, expuestas en `/system/lint` bajo `runtime_violations`. Atrapa lo que el AST no puede (payloads dinámicos). Debe ser O(claves) y nunca lanzar — el sink corre en el hot path de publish.

## Fase 3 (opcional, evolución a contratos formales)

Convención opt-in `domains/{domain}/events.py` con modelos Pydantic de los eventos que el dominio **emite** (el dueño del evento es quien lo publica). El linter — no los plugins — los carga y valida: (a) los publish literales del dominio emisor contra su modelo, (b) los accesos de los consumers contra los campos del modelo. Los consumers nunca importan esos modelos (se mantiene la prohibición cross-domain: el único lector es el linter del dominio system vía filesystem/AST). Añadiría chequeo de tipos, no solo claves. NO implementar hasta validar Fase 1 en uso real.

## Tests (`tests/domains/system/test_event_contract_linter.py`)

Unit tests del analizador con fuentes de plugin como strings fixture (sin filesystem real, usar `ast.parse` directo):
1. publish con dict literal + consumer con Subscript de clave presente → sin findings.
2. Consumer requiere clave que el publish no trae → `MISSING_KEY`.
3. `payload.get("k")` de clave ausente → sin warning (opcional).
4. Dict con `**spread` → sin `MISSING_KEY`.
5. Evento f-string → `DYNAMIC_EVENT` info.
6. Publish sin subscribers → `ORPHAN_PUBLISH`.
7. Alias `p = event.payload; p["x"]` → detecta clave requerida.
8. Test de integración: correr el linter contra los dominios reales del repo y verificar que no produce **warnings** falsos (los infos son aceptables). Nota: `users.WelcomeServicePlugin` consume `user.created` — verificar a mano qué claves usa vs las que publica `CreateUserPlugin` ANTES de dar por bueno el test; si hay una incompatibilidad real, el linter la debe reportar y se arregla el plugin, no el test.

## Criterios de aceptación

- `uv run main.py` arranca y loguea `[EventLinter] ...` con resumen (igual estilo que ArchLinter).
- Introducir a propósito un consumer que lea `event.payload["no_existe"]` → warning `MISSING_KEY` en boot y visible en `GET /system/lint`.
- `uv run -m pytest` en verde.
- Ningún falso warning en el repo actual (los info sí se permiten).
