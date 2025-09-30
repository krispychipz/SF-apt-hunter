"""Minimal subset of pydantic for offline tests."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict


class ValidationError(Exception):
    pass


def Field(**kwargs):  # pragma: no cover - metadata ignored
    return None


def validator(field_name: str):
    def decorator(func: Callable):
        func.__validator_field__ = field_name
        return func

    return decorator


class BaseModel:
    __validators__: Dict[str, list] = {}

    def __init_subclass__(cls) -> None:
        cls.__validators__ = {}
        for name in dir(cls):
            value = getattr(cls, name)
            field = getattr(value, "__validator_field__", None)
            if field:
                cls.__validators__.setdefault(field, []).append(value)

    def __init__(self, **data: Any):
        for key, value in data.items():
            setattr(self, key, value)

    @classmethod
    def parse_obj(cls, obj: dict) -> "BaseModel":
        if not isinstance(obj, dict):
            raise ValidationError("Input must be a dict")
        processed = {}
        annotations = getattr(cls, "__annotations__", {})
        for field, annotation in annotations.items():
            value = obj.get(field)
            if annotation is datetime and isinstance(value, str):
                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"
                try:
                    value = datetime.fromisoformat(value)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
            processed[field] = value
        instance = cls(**processed)
        for field, validators in cls.__validators__.items():
            for func in validators:
                new_value = func(instance, getattr(instance, field))
                if new_value is not None:
                    setattr(instance, field, new_value)
        return instance

    def dict(self) -> dict:
        annotations = getattr(self, "__annotations__", {})
        result = {}
        for field in annotations:
            result[field] = getattr(self, field, None)
        return result


__all__ = ["BaseModel", "Field", "validator", "ValidationError"]
