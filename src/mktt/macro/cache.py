"""Simple TTL cache for Flask — replaces Streamlit's @st.cache_data."""
import time

_cache = {}


def ttl_cache(key, fn, ttl=3600):
    """Return cached value if fresh, otherwise call fn() and cache result."""
    now = time.time()
    if key in _cache:
        val, ts = _cache[key]
        if now - ts < ttl:
            return val
    val = fn()
    _cache[key] = (val, now)
    return val


def invalidate(key=None):
    """Clear one key or entire cache."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()
