"""Run every SQL query in a .sql file against the warehouse and print the results.

Usage:  uv run python -m examples.run_sql examples/stage4_queries.sql
"""

import sys

import duckdb

con = duckdb.connect("data/warehouse.duckdb", read_only=True)  # read-only: queries can't change data
sql_text = open(sys.argv[1]).read()

for statement in con.extract_statements(sql_text):  # split the file into separate queries
    query = statement.query.strip()
    title = next((line for line in query.splitlines() if line.startswith("--")), "-- query")
    print("\n" + "=" * 90 + "\n" + title.lstrip("- ") + "\n" + "=" * 90)
    con.sql(query).show(max_width=200, max_rows=25)
