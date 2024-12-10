"""
Atomic: sugar for threading
"""
import threading
import typing


class AtomicInteger:
    """Atomic integer increment/decrement variable"""
    def __init__(self, value:int = 0):
        self._value = int(value)
        self._lock = threading.Lock()

    def increment(self, step: int = 1) -> int:
        with self._lock:
            self._value += int(step)
            return self._value

    def decrement(self, step: int = 1) -> int:
        return self.increment(-step)

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    @value.setter
    def value(self, value: int) -> None:
        with self._lock:
            self._value = int(value)


class AtomicStrings:
    """Atomic String List"""
    _value: list[str]

    def __init__(self) -> None:
        self._value = []
        self._lock = threading.Lock()


    def append(self, value: str) -> list[str]:
        with self._lock:
            self._value.append(value)
            return self._value

    @property
    def value(self) -> list[str]:
        with self._lock:
            return self._value

    @value.setter
    def value(self, value: list[str]) -> None:
        with self._lock:
            self._value = value

    @property
    def unguarded_value(self) -> list[str]:
        return self._value

class AtomicStringSet:
    """Atomic integer increment/decrement variable"""
    _value: typing.Set[str]

    def __init__(self) -> None:
        self._value = set()
        self._lock = threading.Lock()


    def add(self, value: str) -> typing.Set[str]:
        with self._lock:
            self._value.add(value)
            return self._value

    @property
    def value(self) -> typing.Set[str]:
        with self._lock:
            return self._value

    @value.setter
    def value(self, value: typing.Set[str]) -> None:
        with self._lock:
            self._value = value

    @property
    def unguarded_value(self) -> typing.Set[str]:
        return self._value
