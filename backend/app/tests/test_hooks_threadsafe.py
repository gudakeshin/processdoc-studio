from concurrent.futures import ThreadPoolExecutor

from app.services.hooks import disable_hook, is_hook_disabled


def test_disable_hook_threadsafe_idempotent() -> None:
    name = "concurrency_test_hook"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: disable_hook(name), range(64)))
    assert is_hook_disabled(name) is True

