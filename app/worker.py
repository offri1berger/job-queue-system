import asyncio
import signal

shutdown = False


def handle_sigterm(*args):
    global shutdown
    shutdown = True


signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


async def main():
    # worker loop will be imported and run here
    while not shutdown:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
