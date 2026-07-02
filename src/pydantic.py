"""Small pure-Python subset of Pydantic used by Tau.

This compatibility module keeps Tau installable in restricted Python 3.13
environments where the Rust-backed ``pydantic-core`` wheel is unavailable and
cannot be built. It intentionally implements only the APIs Tau uses.
"""

from __future__ import annotations

import copy
import json
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints


class ValidationError(ValueError):
    """Raised when lightweight model validation fails."""


class _FieldInfo:
    def __init__(self, default: Any = ..., *, default_factory: Any = None, **kwargs: Any) -> None:
        del kwargs
        self.default = default
        self.default_factory = default_factory

    def value(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is ...:
            raise KeyError
        return copy.deepcopy(self.default)


def Field(default: Any = ..., *, default_factory: Any = None, **kwargs: Any) -> Any:
    return _FieldInfo(default, default_factory=default_factory, **kwargs)


def ConfigDict(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


def _is_model_type(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, BaseModel)


def _unwrap_alias(annotation: Any) -> Any:
    return getattr(annotation, "__value__", annotation)


def _model_types(annotation: Any) -> tuple[type[BaseModel], ...]:
    annotation = _unwrap_alias(annotation)
    origin = get_origin(annotation)
    if origin is None:
        return (annotation,) if _is_model_type(annotation) else ()
    if origin is UnionType or str(origin) == "typing.Union":
        found: list[type[BaseModel]] = []
        for arg in get_args(annotation):
            found.extend(_model_types(arg))
        return tuple(found)
    if str(origin) == "typing.Annotated":
        return _model_types(get_args(annotation)[0])
    return ()


def _coerce_value(annotation: Any, value: Any) -> Any:
    annotation = _unwrap_alias(annotation)
    if value is None:
        return None
    origin = get_origin(annotation)
    args = get_args(annotation)
    if str(origin) == "typing.Annotated" and args:
        return _coerce_value(args[0], value)
    if str(origin) == "typing.Literal":
        if args and value not in args:
            raise ValidationError(f"Expected one of {args!r}, got {value!r}")
        return value
    if _is_model_type(annotation):
        if isinstance(value, annotation):
            return value
        if isinstance(value, dict):
            return annotation.model_validate(value)
    if origin is list and args and isinstance(value, list):
        return [_coerce_value(args[0], item) for item in value]
    if origin is dict and len(args) == 2 and isinstance(value, dict):
        return {key: _coerce_value(args[1], item) for key, item in value.items()}
    if origin is UnionType or str(origin) == "typing.Union":
        for model_type in _model_types(annotation):
            if isinstance(value, dict):
                expected_type = _all_annotations(model_type).get("type")
                if expected_type is not None:
                    literals = get_args(expected_type)
                    if literals and value.get("type") not in literals:
                        continue
                try:
                    return model_type.model_validate(value)
                except Exception:
                    continue
        for arg in args:
            try:
                return _coerce_value(arg, value)
            except Exception:
                continue
        return value
    if annotation in {str, int, float, bool} and not isinstance(value, annotation):
        if isinstance(value, (dict, list, tuple, set)):
            raise ValidationError(f"Cannot coerce {type(value).__name__} to {annotation.__name__}")
        if annotation is str:
            raise ValidationError(f"Expected str, got {type(value).__name__}")
        try:
            return annotation(value)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(str(exc)) from exc
    return value


def _to_plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    return value


def _all_annotations(cls: type[Any]) -> dict[str, Any]:
    annotations: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        try:
            resolved = get_type_hints(base, include_extras=True)
        except Exception:  # noqa: BLE001 - fall back for partially initialized classes
            resolved = getattr(base, "__annotations__", {})
        annotations.update(resolved)
    return annotations


class BaseModel:
    model_config: dict[str, Any] = {}

    def __init__(self, **data: Any) -> None:
        annotations = _all_annotations(self.__class__)
        extra = getattr(self.__class__, "model_config", {}).get("extra")
        remaining = dict(data)
        for name, annotation in annotations.items():
            if name == "model_config":
                continue
            if name in remaining:
                raw = remaining.pop(name)
            elif hasattr(self.__class__, name):
                default = getattr(self.__class__, name)
                if isinstance(default, _FieldInfo):
                    raw = default.value()
                else:
                    raw = copy.deepcopy(default)
            else:
                raise ValidationError(f"Missing required field: {name}")
            setattr(self, name, _coerce_value(annotation, raw))
        if remaining and extra == "forbid":
            raise ValidationError(f"Extra fields not permitted: {', '.join(sorted(remaining))}")
        if remaining and extra != "ignore":
            for name, value in remaining.items():
                setattr(self, name, value)

    @classmethod
    def model_validate(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**value)
        raise ValidationError(f"Cannot validate {type(value).__name__} as {cls.__name__}")

    @classmethod
    def model_validate_json(cls, value: str | bytes) -> Any:
        try:
            data = json.loads(value)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(str(exc)) from exc
        return cls.model_validate(data)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        exclude_none = bool(kwargs.get("exclude_none", False))
        annotations = _all_annotations(self.__class__)
        output: dict[str, Any] = {}
        for name in annotations:
            if name == "model_config":
                continue
            value = getattr(self, name)
            if exclude_none and value is None:
                continue
            output[name] = _to_plain(value)
        return output

    def model_dump_json(self, **kwargs: Any) -> str:
        indent = kwargs.get("indent")
        return json.dumps(
            self.model_dump(**kwargs), separators=None if indent else (",", ":"), indent=indent
        )

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> Any:
        data = copy.deepcopy(self.model_dump()) if deep else dict(self.model_dump())
        if update:
            data.update(update)
        return self.__class__.model_validate(data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and self.model_dump() == other.model_dump()

    def __repr__(self) -> str:
        args = ", ".join(f"{key}={value!r}" for key, value in self.model_dump().items())
        return f"{self.__class__.__name__}({args})"


class TypeAdapter:
    def __class_getitem__(cls, item: Any) -> type[TypeAdapter]:
        del item
        return cls

    def __init__(self, annotation: Any) -> None:
        self.annotation = annotation

    def validate_json(self, value: str | bytes) -> Any:
        try:
            data = json.loads(value)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(str(exc)) from exc
        result = _coerce_value(self.annotation, data)
        if isinstance(result, dict):
            raise ValidationError("Could not match union type")
        return result

    def dump_json(self, value: Any, **kwargs: Any) -> bytes:
        indent = kwargs.get("indent")
        return json.dumps(_to_plain(value), separators=None if indent else (",", ":"), indent=indent).encode("utf-8")
