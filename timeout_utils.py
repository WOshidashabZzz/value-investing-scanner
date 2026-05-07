from concurrent.futures import ThreadPoolExecutor, TimeoutError


def run_with_timeout(func, timeout_seconds: float, *args, **kwargs):
    """Run one blocking request with a timeout.

    Returns (True, result) on success, (False, exc) on exception or timeout.
    Threads stuck in vendor SDK calls are not joined, so the batch can continue.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args, **kwargs)
    try:
        return True, future.result(timeout=timeout_seconds)
    except TimeoutError as exc:
        return False, TimeoutError(f"timeout after {timeout_seconds}s")
    except Exception as exc:
        return False, exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
