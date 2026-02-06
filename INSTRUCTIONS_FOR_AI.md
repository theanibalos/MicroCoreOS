# 🤖 AI Development Guide for MicroCoreOS (AI Instructions)

You are a systems architect specialized in resilience and Clean Architecture. Your mission is to extend MicroCoreOS while always protecting the integrity of the **Core** and following modular design standards.

## 🏛️ Philosophy and System Heart (The Core)

The Core is the most important and stable part of MicroCoreOS. It consists of:
- **Kernel**: Resilient orchestrator. Handles non-blocking startup (threading) and dependency injection. **Not to be modified unless for a deep structural improvement.**
- **Container**: Thread-safe central registry (`RLock`). Manages the lifecycle of Tools and stores domain and plugin metadata. Provides total observability.
- **Base Components**: Base classes (`BaseTool`, `BasePlugin`) that define the system contract.

**Golden Rule**: No plugin or tool should compromise the stability of the Kernel. The Core is agnostic to business logic.

> [!IMPORTANT]
> **Sacred Files**: Files within `/core` (Kernel, Container, Registry) are SACRED.
> - **NEVER** modify them to add observability, traceability, or health logic.
> - The architecture is designed for intelligence to grow in Plugins and Tools.
> - If you need to observe the system, use the `event_bus` or the `registry` from a dedicated Plugin.

---

## 🏗️ Execution Architecture

MicroCoreOS is designed to be **Non-Blocking** and **Resilient**:
- **Threaded Startup**: Each plugin initializes in a separate thread to prevent a slow `on_boot()` from freezing the system.
- **EventBus with ThreadPool**: Events are processed via a limited thread pool (Workers) to prevent resource explosion.
- **FastAPI Server**: The HTTP engine is asynchronous and high-performance. Supports **OpenAPI (Swagger)** automatically when you pass Pydantic models when registering endpoints.

---

## 🛠️ How to interact with Tools

**DO NOT** assume how tools work. MicroCoreOS is dynamic.
To use any tool:
1.  **Check `AI_CONTEXT.md`**: It is your "User Manual" updated in real-time by the Kernel.
2.  **Constructor Injection**: Request the tool by its name in your plugin's `__init__`. The Kernel will inject it automatically.
3.  **Isolation**: Tools are raw infrastructure. Plugins are refined logic.
4.  **Swagger/Schemas**: When using `http_server.add_endpoint`, pass your Pydantic models as `request_model` so the API documentation is automatically generated at `/docs`.

---

## 📜 Golden Rules for Plugins

1.  **Memory Isolation**: Communication between domains is **STRICTLY** via `event_bus`. Importing plugins from other domains is prohibited.
2.  **Sovereign Validation**: The Plugin is the guardian. It must validate input data using the static methods of the **Model** before processing anything.
3.  **Single-File Clean Architecture**: In the plugin file, the `execute` method must:
    - **Validate**: Use the Model.
    - **Process**: Pure business logic.
    - **Act**: Use Tools to persist or notify.
    - **Respond**: Always return a dictionary: `{"success": bool, "data": ..., "error": ...}`.

---

## 🚀 Execution and Development

- **Startup Command**: **ALWAYS** use `uv run main.py`. Do not use `python main.py` directly as `uv` ensures dependencies are present.
- **Plugin Location**: `domains/{domain}/plugins/`
- **Model Location**: `domains/{domain}/models/`
- **Tool Location**: `tools/`
- **Contracts**: Review the base classes in `core/`.