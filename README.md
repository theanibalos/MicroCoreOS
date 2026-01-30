# 🚀 MicroOS: AI-First Micro-Kernel Architecture

> **Un Framework diseñado para ser construido, mantenido y operado por Inteligencia Artificial.**

MicroOS no es otro framework web más. Es una arquitectura de **Micronúcleo (Micro-Kernel)** diseñada desde cero para eliminar la ambigüedad que sufren los LLMs al trabajar con frameworks tradicionales. Prioriza la **explicitud estructural** y el **aislamiento** sobre la "magia" o el *syntactic sugar*.

## 🧠 Filosofía: "AI-Native"

En el desarrollo moderno asistido por IA, el cuello de botella no es escribir código, es **mantener el contexto**.
MicroOS resuelve esto con:

1.  **Arquitectura Fractal**: Todo es un Plugin. Todos los Plugins se ven iguales.
2.  **Self-Documenting Context**: El sistema genera y mantiene su propio `AI_CONTEXT.md`, que sirve como "manual de instrucciones vivo" para cualquier agente que trabaje en el repo.
3.  **Sandboxed Logic**: Reglas estrictas de aislamiento. Un plugin corrupto no tumba el Kernel.

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

MicroOS implementa su propio contenedor de inyección y sistema de discovery deliberadamente.
*   **¿Por qué no FastAPI/Flask?**: Para reducir la superficie de API externa que la IA debe conocer. El "Framework" es el código que ves en `/core`, 100% auditable y modificable.
*   **¿Por qué no Celery?**: Para mantener el stack 100% Python nativo y portable sin deps de sistema.

---
*Construido con <3 y Lógica Pura.*
