import asyncio


async def main():
    # scheduler loops will be imported and run concurrently here
    await asyncio.gather(
        asyncio.sleep(0),  # placeholder for loop 1: promote scheduled
        asyncio.sleep(0),  # placeholder for loop 2: crash recovery
        asyncio.sleep(0),  # placeholder for loop 3: orphan recovery
    )


if __name__ == "__main__":
    asyncio.run(main())
