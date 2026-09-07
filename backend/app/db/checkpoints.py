from collections.abc import Generator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver

from app.config import Settings


@contextmanager
def postgres_checkpointer(settings: Settings) -> Generator[PostgresSaver, None, None]:
    """Create the official LangGraph PostgreSQL checkpointer and its managed tables."""
    connection_url = str(settings.database_url).replace("+psycopg", "")
    with PostgresSaver.from_conn_string(connection_url) as checkpointer:
        checkpointer.setup()
        yield checkpointer
