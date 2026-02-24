import signal
import asyncio
from dotenv import load_dotenv
from core.kernel import Kernel

async def main():
    load_dotenv()

    stop_event = asyncio.Event()
    app = Kernel()

    def stop_signal_handler():
        stop_event.set()

    # Native asyncio signal handling
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_signal_handler)

    await app.boot()

    print("\n🚀 [MicroCoreOS] System Online. (Ctrl+C to exit)")

    await stop_event.wait()

    await app.shutdown()
    print("[MicroCoreOS] Shutdown complete. See you soon!")

if __name__ == "__main__":
    asyncio.run(main())