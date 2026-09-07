import logging
import socket
import time

from app.config import get_settings
from app.db.session import create_session_factory
from app.worker import Worker
from app.workflows.runner import WorkflowRunner


def main() -> None:
    settings = get_settings()
    settings.prepare_paths()
    logging.basicConfig(level=settings.log_level)
    runner = WorkflowRunner(settings)
    worker = Worker(create_session_factory(settings), socket.gethostname(), runner.execute)
    while True:
        if not worker.run_once():
            time.sleep(1)


if __name__ == "__main__":
    main()
