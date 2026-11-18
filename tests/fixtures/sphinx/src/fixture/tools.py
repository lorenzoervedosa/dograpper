"""Helpers documented without a module directive, as hand-written references often are."""

from typing import Callable, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class Registry(Generic[K, V]):
    """Values registered under a key."""

    def __init__(self) -> None:
        self._items: dict[K, V] = {}

    def register(self, key: K) -> Callable[[V], V]:
        """Decorator that registers the decorated value under ``key``."""
        def add(value: V) -> V:
            self._items[key] = value
            return value
        return add

    def get(self, key: K, default: V | None = None) -> V | None:
        """The value registered under ``key``, or ``default``."""
        return self._items.get(key, default)


def first(items: list[V], predicate: Callable[[V], bool]) -> V | None:
    """The first item for which ``predicate`` is true, or ``None``."""
    return next((item for item in items if predicate(item)), None)
