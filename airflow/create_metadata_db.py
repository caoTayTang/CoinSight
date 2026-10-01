"""Create Airflow's metadata database on the warehouse PostgreSQL server.

Runs before Airflow starts, so a database volume created before Airflow was
added gets the database too.
"""

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg2


def main() -> None:
    url = os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"].replace("+psycopg2", "")
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    admin_url = urlunsplit(parts._replace(path="/postgres"))

    connection = psycopg2.connect(admin_url)
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("select 1 from pg_database where datname = %s", (name,))
        if cursor.fetchone() is None:
            cursor.execute(f'create database "{name}"')
            print(f"created database {name}")
    connection.close()


if __name__ == "__main__":
    main()
