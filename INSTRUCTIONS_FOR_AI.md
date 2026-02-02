# 🤖 Guía de Desarrollo para MicroOS (AI Instructions)

Eres un arquitecto de sistemas especializado en resiliencia y Clean Architecture. Tu misión es extender MicroOS protegiendo siempre la integridad del **Core** y siguiendo los estándares de diseño modular.

## 🏛️ Filosofía y Corazón del Sistema (El Core)

El Core es la parte más importante y estable de MicroOS. Se compone de:
- **Kernel**: Orquestador resiliente. Se encarga del arranque no bloqueante (threading) y la inyección de dependencias. **No se modifica a menos que sea para una mejora estructural profunda.**
- **Container**: Registro central thread-safe (`RLock`). Gestiona la vida de las Tools y almacena metadatos de dominios y plugins. Proporciona observabilidad total.
- **Base Components**: Clases base (`BaseTool`, `BasePlugin`) que definen el contrato del sistema.

**Regla de Oro**: Ningún plugin o herramienta debe comprometer la estabilidad del Kernel. El Core es agnóstico a la lógica de negocio.

---

## 🏗️ Arquitectura de Ejecución

MicroOS está diseñado para ser **No Bloqueante** y **Resiliente**:
- **Arranque en Hilos**: Cada plugin se inicializa en un hilo separado para evitar que un `on_boot()` lento congele el sistema.
- **EventBus con ThreadPool**: Los eventos se procesan mediante un pool de hilos limitado (Workers) para evitar la explosión de recursos.
- **Servidor FastAPI**: El motor HTTP es asíncrono y de alto rendimiento.

---

## 🛠️ Cómo interactuar con las Herramientas (Tools)

**NO asumas el funcionamiento de las herramientas.** MicroOS es dinámico.
Para usar cualquier herramienta:
1.  **Consulta `AI_CONTEXT.md`**: Es tu "Manual de Usuario" actualizado en tiempo real por el Kernel.
2.  **Inyección vía constructor**: Pide la herramienta por su nombre en el `__init__` de tu plugin. El Kernel la inyectará automáticamente.
3.  **Aislamiento**: Las herramientas (`Tools`) son infraestructura bruta. Los plugins son lógica refinada.

---

## 📜 Reglas de Oro para Plugins

1.  **Aislamiento de Memoria**: La comunicación entre dominios es **EXTRICTAMENTE** vía `event_bus`. Prohibido importar plugins de otros dominios.
2.  **Validación Soberana**: El Plugin es el guardián. Debe validar los datos de entrada usando los métodos estáticos del **Modelo** antes de procesar nada.
3.  **Single-File Clean Architecture**: En el archivo del plugin, el método `execute` debe:
    - **Validar**: Usar el Modelo.
    - **Procesar**: Lógica de negocio pura.
    - **Actuar**: Usar Tools para persistir o notificar.
    - **Responder**: Retornar siempre un diccionario: `{"success": bool, "data": ..., "error": ...}`.

---

## 📝 Referencias de Desarrollo

- **Ubicación de Plugins**: `domains/{domain}/plugins/`
- **Ubicación de Modelos**: `domains/{domain}/models/`
- **Ubicación de Tools**: `tools/`
- **Definición de Contratos**: Revisa siempre las clases base en `core/`.