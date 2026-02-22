# MicroCoreOS Core Architecture (In-Depth Explanation)

This document holds the deep architectural explanation of the three central pillars of MicroCoreOS, its concurrency management, fault tolerance, and the philosophy behind its AI-Agent native design.

---

## 1. The Core Trident

The base architecture is composed of three files that divide responsibilities perfectly: The **Kernel** (Director), the **Container** (Warehouse), and the **Registry** (Whiteboard).

### 1.1 `Container` (The Secure Warehouse)
The `Container` (`container.py`) acts as a **Service Locator** focused on safe concurrency.

- **Single Responsibility:** Store instances of dependencies (Tools) using their name as a key (`"db"`, `"logger"`, `"event_bus"`) and lend them to the plugins that need them.
- **Safety (Threading):** Uses a `threading.RLock()` lock in all its functions (`register`, `get`, `has_tool`). This guarantees that if two execution threads try to access the container at the exact same millisecond, there are no memory collisions that could corrupt the internal dictionary.
- **Fail-Fast Read Behavior:** If a plugin requests a tool using `self.container.get("db")` and it doesn't exist, the program throws an immediate exception to abort before causing silent damage.

### 1.2 `Registry` (The Active Mapping Whiteboard)
The `Registry` (`registry.py`) is the **Active State Mapper** of the system. It executes nothing; it only receives reports from other components.

- **Single Responsibility:** Centralize who is running, who failed, and domain metadata, to feed Observability Dashboards and AI Agents.
- **The Magic: Copy-on-Write:** 
  Instead of blocking the entire system when the Dashboard wants to read the state, the Registry uses `copy.deepcopy()`. 
  - **Writers (The Kernel):** Quickly lock the whiteboard (`_lock`), change a piece of data, and leave.
  - **Readers (Dashboards/Agents):** When calling `get_system_dump()`, they receive a deep "photocopy" of the memory state. They can do whatever they want with that photocopy and send it over the internet, without affecting the locks or the performance of the core application.
- **Intelligence (Business Context):** The `get_domain_metadata()` function reads the raw code of all `models.py` files at boot time and keeps them in RAM. This allows the AI to ask the application's memory *"What fields does the User table have?"* in 0 milliseconds without touching the disk.

### 1.3 `Kernel` (The Finite Orchestra Director)
The `Kernel` (`kernel.py`) orchestrates file loading, dependency injection, and safe booting.

- **Lifecycle (Full Boot):**
  1. **Initialize Tools (Synchronous):** Loads all tools from `tools/` strictly synchronously, one by one. If one fails in its `.setup()`, it notes "FAIL" in the Registry and **does not insert it into the Container**. It moves on, letting the system survive.
  2. **Load and Verify Plugins:** Reads the `plugins/`. Inspects their constructors to see what tools they request (e.g., requests "db"). If the necessary tool is not in the Container because it failed or doesn't exist, the Plugin is marked as "DEAD".
  3. **Start Threads (Boot Plugins):** Starts the `on_boot()` method of each plugin in a different `Daemon` thread concurrently.
  4. **Total Synchronization (Thread Join):** Strictly waits for ALL plugin threads to finish configuring their web routes and subscriptions before proceeding (`for t in boot_threads: t.join()`). **This completely eliminates start-up race conditions.**
  5. **Tool Finalization:** Notifies the tools (`on_boot_complete()`) that they can now start heavy engines (like exposing HTTP ports in Uvicorn).
- **Abdication of the Throne:** The moment it prints *"System Ready"*, **the Kernel ceases to actively exist.** It only waits for you to press `Ctrl+C` to send the shutdown signal (`shutdown()`). The live system is governed by Triggers (HTTP, Event Bus).

---

## 2. Architectural Immortality: Handling Uncaught Exceptions

MicroCoreOS is designed under the **"Resilience through Isolation"** paradigm to avoid crashing the server if product code (written by a rushed human or a chaotic AI) is poorly made.

It uses **Three Shields of Isolation**:

1. **Shield 1: Fast Failure on Boot (The Kernel)**
   The Kernel isolates lethal crashes (bad password in MySQL or bad import) using large wrapping `try/except` blocks during `boot()`. Defective pieces are skipped and declared "DEAD", allowing the system to start without them to serve unaffected areas.

2. **Shield 2: Web Traffic and HTTP Protocols (HttpServerTool)**
   If a plugin's Route Endpoint throws a horrible *ValueError* because a user sent bad data, the exception travels upward. FastAPI (`HttpServerTool`) catches the massive exception internally, logs the error text, and **responds with a tidy `HTTP 500 JSON`**. The web thread cleans itself up and continues accepting clients.

3. **Shield 3: Broken Asynchronous Events (Native Thread Isolation)**
   - If an event is fired and the callback crashes: The `ThreadPoolExecutor` of the `EventBus` isolates that work. The worker-thread absorbs the exception and silences it (with a print to Log), but the other 9 worker-threads continue processing events peacefully.
   - If a parallel thread (`threading.Thread()`) launched manually fails: The OS (Linux) hunts down exclusively the rebel thread and suffocates it. **In Python, errors do not cross the thread barrier.** The main thread (`MainThread`, the web server) will never know about this, guaranteeing massive stability to the core.

---

## 3. Future Philosophy: Contracts, Interfaces, and Databases

### 3.1 Segregated Interfaces (No Magic)
The system relies entirely on the static text of the contracts (For example: `publish`, `subscribe`, `query`, `execute`).

Your base components are interchangeable. Since all Plugins assume the syntactic promise and hide how it works inside, if you wanted to migrate your local and synchronous processing for the giant `Celery/Redis` version:
1. You only rewrite the `.publish()` content inside a new `RedisEventBusTool`.
2. All your Plugins in the repository keep their code untouchably equal to `self.eb.publish("...", data)`.

**Inversion of Control** guarantees infinite forward compatibility.

### 3.2 Raw SQL and Tool Freedom (ORMs Welcome)

It is common to ask if not using an ORM (SQLAlchemy, Prisma) will make it impossible to migrate from PostgreSQL to another database in the future. **MicroCoreOS uses Artificial Intelligence in its favor in this decision, but it is an "Agnostic by Design" architecture:**

**The Default Philosophy: Raw SQL**
MicroCoreOS includes a raw SQL tool by default for the following reasons:
1. **Pure and Direct:** You order plain SQL, you receive Plain Data. All control rests on the DB indexes, not on Python CPU.
2. **AI Refactoring:** If you need to migrate SQLite to PostgreSQL, AI tools can translate a giant block of plain queries from one dialect to another in 5 seconds without errors.
3. **Universal AI Language:** AIs write "Select *" beautifully. They struggle with "local syntax" brought by strange ORMs or APIs prone to changes. Writing SQL guarantees that any AI masters your business.

**Absolute Freedom: Bring your own ORM**
Despite the default philosophy, **MicroCoreOS forbids nothing.**
* If your human team prefers SQLAlchemy or SQLModel, **it is 100% welcome.**
* You just have to create an `orm_tool.py` file, inherit from `BaseTool`, initialize the ORM in `setup()`, and that's it! Your plugins can start requesting `self.orm` from the warehouse and you will still enjoy all the dependency injection and Kernel fault isolation.

The code remains **Zero Boilerplate. Rock Solid. Black and white.**, and the final decision between SQL and ORM always rests in the hands of the software architect of each specific project.
