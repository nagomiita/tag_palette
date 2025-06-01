import time
from functools import wraps


def profile_time(label="処理"):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            duration = (time.perf_counter() - start) * 1000  # ms単位
            print(f"[{label}] {func.__name__} 実行時間: {duration:.2f} ms")
            return result

        return wrapper

    return decorator
