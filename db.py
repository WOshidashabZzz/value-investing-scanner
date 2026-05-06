from urllib.parse import quote_plus
from sqlalchemy import create_engine
from config import DB_CONFIG


def get_engine():
    user = DB_CONFIG["user"]
    password = quote_plus(DB_CONFIG["password"])
    host = DB_CONFIG["host"]
    port = DB_CONFIG["port"]
    database = DB_CONFIG["database"]
    charset = DB_CONFIG["charset"]

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=3600
    )