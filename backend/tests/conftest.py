import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['DEMO_SEED'] = '0'

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.seed import seed_demo


@pytest.fixture()
def db():
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    with s.begin():
        seed_demo(s)
    try:
        yield s
    finally:
        s.close()
