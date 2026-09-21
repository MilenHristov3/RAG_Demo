import os

import psycopg
from dotenv import load_dotenv

load_dotenv(".env")


def get_connection():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


if __name__ == "__main__":
    with get_connection() as conn:
        print("Connected to PostgreSQL!")

        with conn.cursor() as cur:
            cur.execute("select version();")
            print(cur.fetchone()[0])
