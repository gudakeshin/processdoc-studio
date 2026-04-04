from __future__ import annotations

from app.db.session import init_db
from app.services.run_worker import run_redis_worker_loop


def main() -> None:
    init_db()
    run_redis_worker_loop()


if __name__ == "__main__":
    main()
