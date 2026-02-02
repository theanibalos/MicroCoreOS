# 🚀 MicroOS: AI-First Micro-Kernel Architecture

> **Un Framework diseñado para ser construido, mantenido y operado por Inteligencia Artificial.**

MicroOS no es otro framework web más. Es una arquitectura de **Micronúcleo (Micro-Kernel)** diseñada desde cero para eliminar la ambigüedad que sufren los LLMs al trabajar con frameworks tradicionales. Prioriza la **explicitud estructural** y el **aislamiento** sobre la "magia" o el *syntactic sugar*.

## 🧠 Filosofía: "AI-Native"

En el desarrollo moderno asistido por IA, el cuello de botella no es escribir código, es **mantener el contexto**.
MicroOS resuelve esto con:

1.  **Arquitectura Fractal**: Todo es un Plugin. Todos los Plugins se ven iguales.
2.  **Self-Documenting Context**: El sistema genera y mantiene su propio `AI_CONTEXT.md`, que sirve como "manual de instrucciones vivo" para cualquier agente que trabaje en el repo.
3.  **Real Dependency Injection**: Los Plugins no tienen acceso a todo el contenedor. Solo reciben en su constructor las herramientas que piden explícitamente. Seguridad y claridad por diseño.

## 📜 Fundamentos Filosóficos

### Axiomas Core (Verdades Inmutables)

Estos son los principios no negociables que definen MicroOS:

| Axioma | Descripción |
|--------|-------------|
| **Kernel Ciego** | El Kernel no conoce ni debe conocer lógica de negocio. Solo orquesta. |
| **Tool = Stateless + Cross-Domain** | Una Tool provee capacidades técnicas reutilizables sin estado de dominio. |
| **Plugin = Stateful + Domain-Bound** | Un Plugin pertenece a un dominio y puede tener estado de negocio. |
| **Comunicación por Eventos** | Los Plugins NUNCA se llaman directamente. Solo se comunican vía EventBus. |
| **Inyección Declarativa** | Un Plugin declara sus dependencias en el constructor. El Kernel las entrega. |

### Decisiones de Diseño

#### Tool vs Plugin: ¿Cómo decidir?

```
¿Es Tool o Plugin?
├── ¿Tiene estado de dominio?              → Plugin
├── ¿Es reutilizable cross-domain?         → Tool  
└── ¿Implementa reglas de negocio específicas? → Plugin
```

**Ejemplo - Autenticación**:  
- Verificar firma de token (criptografía) → **Tool** (técnica, stateless)  
- Gestionar usuarios y permisos → **Plugin** (estado de dominio, reglas de negocio)

#### Eventos: ¿Síncronos o Asíncronos?

| Método | Cuándo usarlo | Ejemplo |
|--------|---------------|---------|
| `publish(evento, datos)` | NO necesitas confirmación | Notificaciones, logs, side-effects |
| `request(evento, datos)` | NECESITAS la respuesta para continuar | Validaciones cruzadas, consultas |

> ⚠️ **Advertencia**: El abuso de `request()` reintroduce acoplamiento. Si un Plugin hace muchos requests, probablemente debería fusionarse con el dominio que consulta.

#### Orden de Carga

El orden de carga es **irrelevante por diseño**. El sistema se considera listo **solo cuando todo está cargado**. Ningún componente puede asumir que otro ya existe hasta que el Kernel complete el boot.

#### Ciclo de Vida

```
Boot Sequence:
1. Tool.setup()            → Inicialización interna
2. Plugin.__init__()       → Recibe dependencias inyectadas  
3. Plugin.on_boot()        → Registra endpoints, suscripciones
4. Tool.on_boot_complete() → Acciones que requieren sistema completo
5. Sistema Operativo       → Acepta requests externos
```

### Anti-Patterns (Lo Prohibido)

| ❌ Anti-Pattern | ✅ Solución |
|----------------|------------|
| Plugin importa otro Plugin | Comunicación vía EventBus |
| Plugin accede al Container | Declarar dependencia en `__init__` |
| Tool con lógica de negocio | Mover a Plugin en dominio apropiado |
| Estado compartido sin Tool | Usar `state` Tool con namespaces |

### Principios de Extensibilidad

| Necesidad | Acción |
|-----------|--------|
| Nueva capacidad técnica | Crear Tool en `tools/` |
| Nueva funcionalidad de negocio | Crear Plugin en `domains/{dominio}/plugins/` |
| Nueva feature cross-domain | Crear nuevo dominio con sus plugins |
| Reemplazar infraestructura | Crear Tool con mismo `name` property |

## 🏗️ Arquitectura del Sistema

### 1. El Kernel (`core/`)
El cerebro ciego. No conoce el negocio. Su única función es:
*   Escanear directorios (`tools/` y `domains/`).
*   Cargar clases dinámicamente.
*   Inyectar dependencias (`Container`).
*   Manejar el ciclo de vida (Boot/Shutdown).

### 2. Tools (`tools/`)
La infraestructura agnóstica. Proveen capacidades técnicas, no de negocio.
*   **db**: Abstracción de base de datos (SQLite default).
*   **http_server**: Servidor web ligero.
*   **event_bus**: Columna vertebral de comunicación desacoplada.
*   **state**: Memoria compartida volátil.
*   **context_manager**: Generador de contexto para la IA.

### 3. Domains & Plugins (`domains/`)
Donde vive la lógica de negocio.
*   **Estructura**: `domains/{nombre}/plugins/` y `domains/{nombre}/models/`.
*   **Regla de Oro**: Un dominio NUNCA importa otro dominio. Se comunican SOLO vía eventos.
*   **Plugins**: Unidades atómicas de ejecución (`execute(**kwargs)`). Siguen el patrón *Single-File Clean Architecture*.

## 🚀 Quick Start

### Requisitos
*   Python 3.10+
*   `uv` (recomendado) o `pip`

### Ejecución
```bash
# Instalar dependencias y correr
uv run main.py
```

El sistema iniciará el Kernel, cargará las Tools, descubrirá los Plugins y levantará el servidor HTTP (por defecto en puerto 5000).

## 👩‍💻 Guía de Desarrollo (para IAs y Humanos)

Si eres un humano (o una IA) que va a extender este sistema, lee **`INSTRUCTIONS_FOR_AI.md`**.

Resumen rápido para crear un Plugin:

1.  Define tu **Modelo** en `domains/{tu_dominio}/models/`.
2.  Crea tu **Plugin** en `domains/{tu_dominio}/plugins/`.
3.  Hereda de `BasePlugin`.
4.  Implementa `execute(self, **kwargs)`.
5.  ¡Listo! El Kernel lo cargará automáticamente en el próximo reinicio.

## 🛡️ "Not Invented Here" Statement

MicroOS implementa su propio sistema de **Inyección de Dependencias (DI)** y orquestación deliberadamente.
*   **¿Por qué no FastAPI/Flask?**: Para reducir la superficie de API externa que la IA debe conocer. El "Framework" es el código que ves en `/core`, 100% auditable y modificable.
*   **¿Por qué no Inyectores externos?**: Para mantener la transparencia. El Kernel es un orquestador que puedes leer en un minuto y entender exactamente cómo se inyectan tus herramientas.

## 🗺️ Roadmap de MicroOS

El sistema está en evolución. Próximas capacidades planificadas:

- **Middleware / Hooks**: Capacidad de interceptar ejecuciones de plugins para auditoría, seguridad o métricas globales.
- **Observability (Telemetría)**: Integración nativa con OpenTelemetry para trazado distribuido de eventos.
- **Plugins Políglotas**: Soporte para plugins en otros lenguajes vía WASM o gRPC, manteniendo al Kernel como orquestador central.

---
*Construido con <3 y Lógica Pura.*
