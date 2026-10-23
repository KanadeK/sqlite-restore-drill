"""Create a small synthetic CLOSED backup, refusing to replace an existing file."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
    # Claim the output before SQLite's create-if-missing behavior can open it.
    with path.open("xb"):
        pass
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL);"
            "INSERT INTO notes VALUES (1, 'Synthetic first note'), (2, 'Synthetic second note');"
            "PRAGMA user_version=2;"
        )
    print("Synthetic backup created. The connection is closed.")


if __name__ == "__main__":
    main()
