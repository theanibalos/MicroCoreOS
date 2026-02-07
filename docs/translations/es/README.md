# MicroCoreOS

> Cada vez que le pedía a mi IA que añadiera un endpoint CRUD,  
> intentaba crear 6-8 archivos. Me cansé de eso.

**1 archivo = 1 funcionalidad.** Esa es la idea base.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## El Problema

Los asistentes de IA como Cursor y Claude necesitan entender tu arquitectura para añadir funcionalidades.

En arquitecturas tradicionales de capas, eso significa explicar:
- Dónde poner la entidad
- Cómo cablear el repositorio
- Qué factoría crea el caso de uso
- Cómo el controlador mapea a la ruta
- Qué DTOs crear

**Son 6-8 archivos y más de 200 líneas de código para un solo endpoint.**

## La Solución

```python
# domains/products/plugins/create_product_plugin.py
from core.base_plugin import BasePlugin

class CreateProductPlugin(BasePlugin):
    def __init__(self, http_server, db, logger, event_bus):
        self.http = http_server
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        self.http.add_endpoint("/products", "POST", self.execute)

    def execute(self, data: dict):
        product_id = self.db.execute(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            (data["name"], data["price"])
        )
        self.bus.publish("product.created", {"id": product_id})
        return {"success": True, "id": product_id}
```

**48 líneas. Un archivo. Funcionalidad completa.**

- ✅ Registro de endpoint
- ✅ Operación de base de datos
- ✅ Publicación de eventos
- ✅ Auto-descubierto por el kernel
- ✅ Dependencias inyectadas automáticamente

---

## Para Desarrollo Dirigido por IA

La arquitectura genera `AI_CONTEXT.md` automáticamente—un manifiesto con todas las herramientas disponibles y sus firmas. Tu asistente de IA siempre sabe qué hay disponible sin tener que explorar todo el código.

**Uso de tokens medido por funcionalidad:**

| Arquitectura | Archivos | Líneas | Tokens Est. |
|--------------|----------|--------|-------------|
| **MicroCoreOS** | 1 | ~50 | ~1,000 |
| Vertical Slice | 2-3 | ~100 | ~1,500 |
| N-Layer | 4-5 | ~150 | ~2,500 |
| Hexagonal | 5-7 | ~200 | ~3,500 |
| Clean Architecture | 6-8 | ~250 | ~4,000 |

---

## 🚀 MicroCoreOS: Arquitectura Atomic Microkernel

MicroCoreOS no es solo un framework; es una **propuesta de arquitectura de Micronúcleo (Micro-Kernel)**. Su diseño busca eliminar la "caja negra" de los sistemas tradicionales, permitiendo que tanto humanos como IAs puedan razonar, auditar y extender el sistema con eficiencia. Se basa en tres pilares: **Microkernel**, **Fractalidad** y **Modularidad total**.

## 🧠 Filosofía: "Human-Auditable, AI-Ready"

MicroCoreOS busca la **transparencia total**. Aunque el Kernel y las herramientas proveen la base estable, la complejidad del sistema crece de forma **fractal** a través de sus plugins.

1.  **Arquitectura Fractal (en la Capa de Ejecución)**: Los Plugins son las unidades que escalan. Todos los Plugins siguen el mismo patrón estructural, lo que los hace predecibles. Si entiendes un plugin, entiendes toda la lógica de negocio del sistema.
2.  **Real Dependency Injection**: Los Plugins no tienen acceso al contenedor global. Solo reciben en su constructor las herramientas que piden explícitamente. Esto garantiza seguridad, evita efectos secundarios y permite una claridad absoluta sobre lo que cada pieza necesita para funcionar.
3.  **Auditabilidad Extrema**: Al aislar cada funcionalidad en su propio plugin con dependencias explícitas, un humano puede auditar el 100% del impacto de un cambio en segundos.
4.  **IA como Facilitador**: La IA es un caso de uso potente (ej. para el contexto de agentes), pero el sistema está construido para ser robusto y comprensible para cualquier desarrollador.

## 📜 Fundamentos Filosóficos

### Axiomas Core (Verdades Inmutables)

Estos son los principios no negociables que definen MicroCoreOS:

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

## Para Equipos

En arquitecturas tradicionales, una sola funcionalidad requiere coordinación:
- Alguien es dueño de la capa de dominio
- Alguien es dueño de la infraestructura
- Alguien cablea la inyección de dependencias
- Alguien revisa los cambios entre capas

**En MicroCoreOS: 1 persona, 1 archivo, 1 PR.**

### Por qué las Tools son Stateless

Las Tools no guardan estado de negocio—son pura infraestructura. Esto significa:

- **Cambio de base de datos instantáneo**: Reemplaza la Tool `db` por PostgreSQL, MongoDB o un ORM. Los plugins no cambian.
- **Sin riesgo de migración**: Las Tools son intercambiables por diseño.
- **En la era del código barato**: Tu IA escribe el SQL en 2 segundos. ¿Para qué abstraerlo?

### Misma Aislamiento, Menos Ceremonia

| Beneficio Tradicional | Equivalente en MicroCoreOS |
|----------------------|----------------------------|
| "Cambiar DB sin tocar lógica" | Cambia la Tool, no el Plugin |
| "Testear capas en aislamiento" | Mockea las Tools en tests de plugin |
| "Límites de propiedad claros" | 1 plugin = 1 responsable |
| "Onboarding de nuevos devs" | Lee AI_CONTEXT.md en 5 minutos |

---

## 🛡️ "Not Invented Here" Statement

MicroCoreOS implementa su propio sistema de **Inyección de Dependencias (DI)** y orquestación deliberadamente.
*   **¿Por qué no FastAPI/Flask?**: Para reducir la superficie de API externa que la IA debe conocer. El "Framework" es el código que ves en `/core`, 100% auditable y modificable.
*   **¿Por qué no Inyectores externos?**: Para mantener la transparencia. El Kernel es un orquestador que puedes leer en un minuto y entender exactamente cómo se inyectan tus herramientas.

## 🗺️ Roadmap y Ecosistema Futuro

MicroCoreOS está diseñado para que su **Kernel** sea casi inmutable. El crecimiento no vendrá de cambiar el núcleo, sino de construir un framework robusto encima mediante la expansión de Tools y capacidades de observabilidad:

- **Observabilidad con Propósito**: El `EventBus` puede evolucionar para incluir un **Tracer** integrado que mapee exactamente qué plugins reaccionan a qué eventos y cuánto tardan.
- **Framework de Producción**: Las Tools actuales (como SQLite) son **implementaciones de referencia**. Se espera que el implementador desarrolle sus propias Tools (con migraciones, ORM, validaciones avanzadas) según sus necesidades.
- **Middleware Global**: Capacidad de interceptar ejecuciones de plugins para auditoría o seguridad sin tocar el Kernel.
- **Plugins Políglotas**: Soporte para otros lenguajes vía WASM o gRPC, manteniendo al Kernel como el orquestador central inmutable.


## ⚡ Consideraciones de Alto Rendimiento

Si tu implementación de MicroCoreOS requiere atacar operaciones de rendimiento extremo (motores de juego, procesamiento de video 4K o HFT), considera las siguientes optimizaciones:

### 1. Despacho Estático (Static DI)
La Inyección de Dependencias dinámica tiene un costo de "indirección" (abrir el cajón para buscar el puntero). Para velocidad **instantánea**:
*   **Code Generation**: Usa herramientas que generen el cableado de dependencias al compilar. Esto permite al compilador realizar *Inlining*, eliminando el overhead de la llamada por completo.

### 2. El "Grial" del Zero-Copy
Para manejar grandes volúmenes de datos (ej. Frames de video) entre plugins:
*   **Punteros de Propiedad**: En lenguajes como **Rust**, utiliza `Arc` (Atomic Reference Counting). Esto permite que múltiples plugins lean la **misma memoria física** simultáneamente sin copiar ni un solo byte, manteniendo la seguridad de hilos.

### 3. La Regla de Oro del EventBus
*   **Orquestación vs Procesamiento**: El EventBus es para **avisar**, no para **trabajar**. 
*   Si una operación es crítica y se repite millones de veces por segundo, debe vivir como **lógica interna** del plugin o como una herramienta inyectada directamente. Evita cruzar el bus de eventos para micro-operaciones.

### 4. Selección de Lenguaje según Latencia
| Lenguaje | Perfil | Ideal para... |
|----------|--------|---------------|
| **Python** | Context-Efficient | Prototipado rápido, APIs, Lógica IA |
| **Go** | Throughput-Optimal | Microservicios de alto tráfico |
| **Rust** | Latency-Extreme | Motores, Vídeo, Sistemas en Tiempo Real |

---
*Construido con <3 y Lógica Pura.*
