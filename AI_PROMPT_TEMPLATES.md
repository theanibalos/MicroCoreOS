# 🤖 MicroCoreOS AI Prompt Templates

Use these prompt templates with your AI assistant (Cursor, Copilot, Claude, ChatGPT, etc.) to quickly generate new Features (Plugins) and Infrastructure (Tools) following the exact rules of the Atomic Microkernel Architecture.

---

## 🚀 1. Prompt for Creating a New Feature (Plugin)

**When to use:** When you need a new HTTP endpoint, a background job, an event listener, or any piece of domain business logic.

**Copy & Paste this prompt:**

```text
Act as an expert in MicroCoreOS architecture. I need you to create a new Feature (Plugin) for the domain "[NAME_OF_DOMAIN]". 

The feature must do the following:
[DESCRIBE_THE_FEATURE_HERE (e.g., "An endpoint to create a new user and save it in the database", "Listen to the event 'product.created' and send an email")]

Follow the MicroCoreOS CRITICAL RULES strictly:
1. Create ONE single file inside `domains/[NAME_OF_DOMAIN]/plugins/`.
2. Do NOT create Data Transfer Objects (DTOs), Services, Controllers, or Repositories. Put ALL the logic inside this single plugin file.
3. The class must inherit from `BasePlugin`.
4. Inject the necessary Tools via the `__init__` constructor arguments (e.g., `logger`, `db`, `http`, `event_bus`). DO NOT import tools manually.
5. In the `__init__` method, ONLY save the injected tools as instance attributes (e.g., `self.db = db`). Do not put logic here.
6. Register endpoints, web-sockets, or event subscriptions inside the `on_boot(self)` method.
7. Implement the core business logic inside an `execute(self, ...)` or similar handler method.
8. The code must be concise, clean, and use the existing Dependency Injection container pattern.
```

---

## 🔧 2. Prompt for Creating a New Infrastructure Tool

**When to use:** When you need the system to communicate with a new external system, protocol, or library (e.g., Redis, external API, Stripe, AWS S3).

**Copy & Paste this prompt:**

```text
Act as an expert in MicroCoreOS architecture. I need you to create a new Infrastructure Tool called "[NAME_OF_TOOL]". 

The tool must wrap the following capability/technology:
[DESCRIBE_THE_TECHNOLOGY_HERE (e.g., "A Redis client for connecting to a caching cluster", "A wrapper around the Stripe API for payments")]

Follow the MicroCoreOS CRITICAL RULES strictly:
1. Create ONE single file at `tools/[NAME_OF_TOOL]/[NAME_OF_TOOL]_tool.py`.
2. The class must inherit from `BaseTool`.
3. Implement the `name` property returning exactly "[NAME_OF_TOOL]" as a string.
4. Implement the `setup(self)` method to allocate resources (load configs from env, establish connections).
5. Implement the `get_interface_description(self) -> str` method. This MUST return a highly descriptive string detailing the "PURPOSE" and "CAPABILITIES" of the tool so that AI agents can understand how to use it later via the AI_CONTEXT.md.
6. (Optional) If the tool needs to interact with other tools after everything is loaded, implement `on_boot_complete(self, container)`.
7. Implement `shutdown(self)` for graceful cleanup (closing sockets, stopping threads).
8. Make the tool fully STATELESS concerning business logic. It should only provide technical capabilities.
```

---

## 📜 3. Prompt for Refactoring standard code to MicroCoreOS

**When to use:** When you have existing code (like a FastAPI router or a typical MVC N-Layer service) and want to migrate it to the Microkernel pattern.

**Copy & Paste this prompt:**

```text
Act as an expert in MicroCoreOS architecture. I have the following traditional backend code and I want to migrate it to a MicroCoreOS Plugin.

Target Domain: "[NAME_OF_DOMAIN]"

[PASTE_YOUR_EXISTING_CODE_HERE]

Instructions for the migration:
1. Condense the Router, Service, and Repository logic into a single Plugin file.
2. Eliminate any hardcoded imports of databases or external instance singletons.
3. Identify the required infrastructure capabilities (e.g., database queries, HTTP, logging) and request them via the `__init__` parameters using the tools (`db`, `http`, `logger`, `config`).
4. Move the route or event registration to the `on_boot(self)` method.
5. Keep the solution within a single file under `domains/[NAME_OF_DOMAIN]/plugins/`.
```
