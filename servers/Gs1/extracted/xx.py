import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = input("Paste your MongoDB URI: ").strip()

async def fix():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["ffglory"]

    indexes = await db.sessions.index_information()
    print("Current indexes:", list(indexes.keys()))

    if "token_1" in indexes:
        await db.sessions.drop_index("token_1")
        print("Dropped token_1 index")
    else:
        print("token_1 not found — checking for null docs...")

    # Clear any null-token sessions
    result = await db.sessions.delete_many({"token": None})
    print(f"Deleted {result.deleted_count} null-token sessions")

    indexes_after = await db.sessions.index_information()
    print("Indexes now:", list(indexes_after.keys()))

    await client.close()

asyncio.run(fix())