import sys
import signal
import asyncio
from dotenv import load_dotenv
from core.kernel import Kernel

async def _main():
    load_dotenv()
    stop_event = asyncio.Event()
    app = Kernel()

    def stop_signal_handler():
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_signal_handler)

    try:
        await app.boot()
        print("\n🚀 [MicroCoreOS] System Online. (Ctrl+C to exit)")
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await app.shutdown()
        print("[MicroCoreOS] Shutdown complete. See you soon!")

def main():
    if "--boot-tool" in sys.argv:
        # Pipeline mode: boot ONE tool in isolation and exit. Which tool and
        # with which env vars is deployment configuration, not code here.
        idx = sys.argv.index("--boot-tool")
        if idx + 1 >= len(sys.argv):
            print("Usage: uv run main.py --boot-tool <tool_name>")
            sys.exit(2)
        load_dotenv()
        asyncio.run(Kernel().boot_tool(sys.argv[idx + 1]))
        return
    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

if __name__ == "__main__":
    main()
