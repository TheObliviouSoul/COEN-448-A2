"""
Shared payload validation helpers used across the microservices.
"""

from __future__ import annotations

import re
from typing import Any


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DELIVERY_ADDRESS_FIELDS = ("street", "city", "state", "postalCode", "country")


def ensure_json_object(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Invalid JSON data")
    return data


def ensure_email_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be an array of valid email addresses")
    if not all(isinstance(email, str) and EMAIL_PATTERN.match(email) for email in value):
        raise ValueError(f"{field_name} must be an array of valid email addresses")


def ensure_delivery_address(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("deliveryAddress must be an object")

    for field in DELIVERY_ADDRESS_FIELDS:
        field_value = value.get(field)
        if not isinstance(field_value, str) or not field_value.strip():
            raise ValueError(f"deliveryAddress must contain a valid {field}")
