# init_db.py
# this initilises the database only needs to be run once
# init_db.py
from sqlalchemy import create_engine
from models import Base
from config import Config

config = Config(__file__)
engine = create_engine(config.database.connection_string)

# sqlite_sequence is an internal SQLite table, skip it
tables_to_create = [t for name, t in Base.metadata.tables.items() if name != 'sqlite_sequence']
Base.metadata.create_all(engine, tables=tables_to_create)
print("Done — tables created in metrics.db")