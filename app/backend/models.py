from sqlalchemy import Table, Column, Integer, String, DateTime, MetaData

metadata = MetaData()

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", String),
    Column("start_time", DateTime),
    Column("end_time", DateTime),
    Column("description", String),
)