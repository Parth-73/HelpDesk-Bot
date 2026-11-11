"""Manual database diagnostic. Importing this module never opens a live connection."""
from pathlib import Path
import sys


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from app.config import Settings
    import psycopg
    url=Settings().database_url.get_secret_value().replace('postgresql+psycopg://','postgresql://',1)
    if not url:
        print('Configure DATABASE_URL in backend/.env.');return 1
    try:
        with psycopg.connect(url,connect_timeout=10,prepare_threshold=None) as connection:
            connection.execute('SELECT 1').fetchone()
        print('PostgreSQL connection succeeded.');return 0
    except psycopg.Error as error:
        print(f'PostgreSQL connection failed ({type(error).__name__}). Check the URL, password, SSL and network access.');return 1

if __name__=='__main__': raise SystemExit(main())
