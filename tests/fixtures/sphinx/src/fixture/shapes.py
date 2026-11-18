"""Shapes and the boxes that store them.

Typical use::

    box = Box.of("apple")
    box.put("pear")
"""

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar, overload

T = TypeVar("T")
U = TypeVar("U")

#: Name given to a shape that has none.
DEFAULT_NAME = "shape"


class Shape:
    """A named shape."""

    #: Number of sides; 0 for a curve.
    sides: int = 0

    def __init__(self, name: str = DEFAULT_NAME) -> None:
        self._name = name

    @property
    def name(self) -> str:
        """The shape's name."""
        return self._name

    def area(self) -> float:
        """Area of the shape.

        :raises NotImplementedError: when the shape does not define it
        """
        raise NotImplementedError


class Box(Shape, Generic[T]):
    """A generic box that stores items in insertion order.

    :param items: the first items
    """

    #: Most items a box can hold.
    CAPACITY: int = 16

    class Lid:
        """The lid of a box."""

        def is_closed(self) -> bool:
            """Whether the lid is on the box."""
            return True

    def __init__(self, items: list[T] | None = None) -> None:
        super().__init__("box")
        self.items: list[T] = list(items or [])

    @classmethod
    def of(cls, *items: T) -> "Box[T]":
        """Wrap values in a new box.

        :param items: the values to wrap
        :returns: a box holding ``items``
        """
        return cls(list(items))

    @staticmethod
    def fits(count: int) -> bool:
        """Whether ``count`` items fit in one box."""
        return count <= Box.CAPACITY

    @property
    def size(self) -> int:
        """Number of stored items."""
        return len(self.items)

    def put(self, item: T) -> None:
        """Store one item.

        :param item: the item to store
        :raises BoxFullError: when the box already holds ``CAPACITY`` items
        """
        if len(self.items) >= self.CAPACITY:
            raise BoxFullError(self.CAPACITY)
        self.items.append(item)

    def map(self, func: Callable[[T], U]) -> "Box[U]":
        """A new box with ``func`` applied to every item."""
        return Box([func(item) for item in self.items])

    def shake(self, times: int) -> None:
        pass


@dataclass(frozen=True)
class Point:
    """A point on the grid."""

    #: Horizontal position.
    x: int
    #: Vertical position.
    y: int = 0

    def moved(self, dx: int, dy: int) -> "Point":
        """This point moved by ``dx`` and ``dy``."""
        return Point(self.x + dx, self.y + dy)


class ShapeError(Exception):
    """Base class of the errors raised by shapes."""


class BoxFullError(ShapeError):
    """The box already holds its capacity.

    :param capacity: the capacity that was reached
    """

    def __init__(self, capacity: int) -> None:
        super().__init__(f"box is full ({capacity} items)")
        self.capacity = capacity


def apply(func: Callable[[T], U], items: list[T]) -> list[U]:
    """Apply ``func`` to every item.

    :param func: the function to apply
    :param items: the items to transform
    :returns: the results, in the order of ``items``
    """
    return [func(item) for item in items]


@overload
def scale(value: int, factor: int) -> int: ...
@overload
def scale(value: float, factor: float) -> float: ...
def scale(value, factor):
    """Multiply ``value`` by ``factor``, keeping its type."""
    return value * factor
