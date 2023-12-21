from datetime import datetime
import json
import psycopg2
from psycopg2.sql import SQL, Identifier


class PostgresManager:
    """
    A class to manage postgres connections and queries
    """

    def __init__(self):
        self.conn = None
        self.cur = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    def connect_with_url(self, url):
        self.conn = psycopg2.connect(url)
        self.cur = self.conn.cursor()

    def close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    def run_sql(self, sql) -> str:
        """
        Run a SQL query against the postgres database
        """
        self.cur.execute(sql)
        columns = [desc[0] for desc in self.cur.description]
        res = self.cur.fetchall()

        list_of_dicts = [dict(zip(columns, row)) for row in res]

        json_result = json.dumps(list_of_dicts, indent=4, default=self.datetime_handler)

        return json_result

    def datetime_handler(self, obj):
        """
        Handle datetime objects when serializing to JSON.
        """
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)  # or just return the object unchanged, or another default value

    def get_table_definition(self, table_name):
        """
        Generate the 'create' definition for a table
        """

        # get_def_stmt = """
        # SELECT pg_class.relname as tablename,
        #     pg_attribute.attnum,
        #     pg_attribute.attname,
        #     format_type(atttypid, atttypmod)
        # FROM pg_class
        # JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
        # JOIN pg_attribute ON pg_attribute.attrelid = pg_class.oid
        # WHERE pg_attribute.attnum > 0
        #     AND pg_class.relname = %s
        #     AND pg_namespace.nspname = 'public'  -- Assuming you're interested in public schema
        # """

        get_def_stmt = """
        SELECT
            ft.foreign_table_schema as schema_name,
            ft.foreign_table_name as table_name,
            a.attname as column_name,
            format_type(a.atttypid, a.atttypmod) as column_type,
            d.description as column_description
        FROM
            information_schema.foreign_tables ft
        JOIN
            pg_foreign_table pft ON ft.foreign_table_name = pft.ftrelid::regclass::text
        JOIN
            pg_attribute a ON a.attrelid = pft.ftrelid
        LEFT JOIN
            pg_description d ON a.attrelid = d.objoid AND a.attnum = d.objsubid
        WHERE
            ft.foreign_table_schema = 'akeyless'
            AND a.attnum > 0
        ORDER BY
            ft.foreign_table_schema,
            ft.foreign_table_name,
            a.attnum;
        """
        self.cur.execute(get_def_stmt, (table_name,))
        rows = self.cur.fetchall()
        create_table_stmt = "CREATE TABLE {} (\n".format(table_name)
        for row in rows:
            create_table_stmt += "{} {},\n".format(row[2], row[3])
        create_table_stmt = create_table_stmt.rstrip(",\n") + "\n);"
        return create_table_stmt

    def get_all_table_names(self):
        """
        Get all table names in the database
        """
        # get_all_tables_stmt = (
        #     "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
        # )
        get_all_tables_stmt = (
            "SELECT foreign_table_name FROM information_schema.foreign_tables WHERE foreign_table_schema = 'akeyless';"
        )
        self.cur.execute(get_all_tables_stmt)
        return [row[0] for row in self.cur.fetchall()]

    def get_table_definitions_for_prompt(self):
        """
        Get all table 'create' definitions in the database
        """
        table_names = self.get_all_table_names()
        definitions = []
        for table_name in table_names:
            definitions.append(self.get_table_definition(table_name))
        return "\n\n".join(definitions)

    def get_table_definition_map_for_embeddings(self):
        """
        Creates a map of table names to table definitions
        """
        table_names = self.get_all_table_names()
        definitions = {}
        for table_name in table_names:
            definitions[table_name] = self.get_table_definition(table_name)
        return definitions

    def get_related_tables(self, table_list, n=2):
        """
        Get tables that have foreign keys referencing the given table
        """

        related_tables_dict = {}

        for table in table_list:
            # # Query to fetch tables that have foreign keys referencing the given table
            # self.cur.execute(
            #     """
            #     SELECT 
            #         a.relname AS table_name
            #     FROM 
            #         pg_constraint con 
            #         JOIN pg_class a ON a.oid = con.conrelid 
            #     WHERE 
            #         confrelid = (SELECT oid FROM pg_class WHERE relname = %s)
            #     LIMIT %s;
            #     """,
            #     (table, n),
            # )


            # Query to fetch foreign tables that have foreign keys referencing the given foreign table
            self.cur.execute(
                """
                SELECT 
                    ft.foreign_table_name AS table_name
                FROM 
                    information_schema.foreign_table_constraints AS ftc
                    JOIN information_schema.foreign_tables AS ft 
                        ON ft.foreign_table_name = ftc.foreign_table_name
                        AND ft.foreign_table_schema = ftc.foreign_table_schema
                WHERE 
                    ftc.unique_constraint_schema = 'akeyless'
                    AND ftc.unique_constraint_name = (
                        SELECT 
                            tc.constraint_name 
                        FROM 
                            information_schema.table_constraints AS tc
                            JOIN information_schema.constraint_column_usage AS ccu 
                                ON ccu.constraint_name = tc.constraint_name
                        WHERE 
                            tc.constraint_schema = 'akeyless'
                            AND tc.table_name = %s
                            AND tc.constraint_type = 'FOREIGN KEY'
                    )
                LIMIT %s;
                """,
                (table, n),
            )

            related_tables = [row[0] for row in self.cur.fetchall()]

            # # Query to fetch tables that the given table references
            # self.cur.execute(
            #     """
            #     SELECT 
            #         a.relname AS referenced_table_name
            #     FROM 
            #         pg_constraint con 
            #         JOIN pg_class a ON a.oid = con.confrelid 
            #     WHERE 
            #         conrelid = (SELECT oid FROM pg_class WHERE relname = %s)
            #     LIMIT %s;
            #     """,
            #     (table, n),
            # )


            # Query to fetch foreign tables that the given foreign table references
            self.cur.execute(
                """
                SELECT 
                    ft.foreign_table_name AS referenced_table_name
                FROM 
                    information_schema.foreign_table_constraints AS ftc
                    JOIN information_schema.foreign_tables AS ft 
                        ON ft.foreign_table_name = ftc.referenced_table_name
                        AND ft.foreign_table_schema = ftc.referenced_table_schema
                WHERE 
                    ftc.foreign_table_schema = 'akeyless'
                    AND ftc.foreign_table_name = %s
                    AND ftc.constraint_type = 'FOREIGN KEY'
                LIMIT %s;
                """,
                (table, n),
            )


            related_tables += [row[0] for row in self.cur.fetchall()]

            related_tables_dict[table] = related_tables

        # convert dict to list and remove dups
        related_tables_list = []
        for table, related_tables in related_tables_dict.items():
            related_tables_list += related_tables

        related_tables_list = list(set(related_tables_list))

        return related_tables_list
