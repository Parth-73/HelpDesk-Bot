import asyncio
import os
import sys
import uvicorn

if __name__ == '__main__':
    config = uvicorn.Config('app.main:app', host='0.0.0.0', port=int(os.getenv('PORT', '8000')), workers=1, loop='asyncio', access_log=False)
    # Recent Uvicorn defaults to Proactor on Windows; psycopg requires Selector.
    asyncio.run(uvicorn.Server(config).serve(), loop_factory=asyncio.SelectorEventLoop if sys.platform == 'win32' else None)
