from dataclasses import asdict, is_dataclass
from typing import Any


def to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return to_plain_data(asdict(value))
    if isinstance(value, dict):
        return {key: to_plain_data(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [to_plain_data(child) for child in value]
    if isinstance(value, list):
        return [to_plain_data(child) for child in value]
    return value
