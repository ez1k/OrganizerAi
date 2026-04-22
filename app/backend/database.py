from sqlalchemy import create_engine

DB_CONNECTION = (
    "mssql+pyodbc://@DESKTOP-SN6B47K/OrganizerDB"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
)

engine = create_engine(DB_CONNECTION)