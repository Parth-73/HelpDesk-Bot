import asyncio
import sys
from .config import Settings
from .database import Database


async def main():
    db = Database(Settings())
    try:
        await db.initialize()
        print('Database schema and usage counters initialized.')
    finally:
        await db.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print(f'Database initialization failed ({type(error).__name__}). Check DATABASE_URL, database availability and SSL settings.', file=sys.stderr)
        sys.exit(1)
