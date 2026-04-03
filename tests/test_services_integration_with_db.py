"""
Assignment integration test coverage.

Requirements:
- REQ-1.1: Validate REST API endpoints work as expected across services.
- REQ-1.2: Validate API Gateway routing to the correct microservice.
- REQ-1.3: Validate strangler-pattern routing between User Service v1 and v2.
- REQ-2.1: Validate user updates propagate to the Order Service via RabbitMQ.
- REQ-3.1: Confirm user-detail changes are reflected in linked order details.

Test cases:
- TC_01: Validate user creation and retrieval.
- TC_02: Validate order creation with an existing user.
- TC_03: Validate event-driven user update propagation.
- TC_04: Validate API Gateway routing between user-service versions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
import requests
from dotenv import dotenv_values
from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.test.yml"
TEST_ENV_FILE = ROOT / "tests" / ".env.integration"
PROJECT_NAME = "aware-a2-tests"
API_BASE_URL = "http://localhost:8000"
ADMIN_BASE_URL = "http://localhost:8001"
REQUEST_TIMEOUT = 15
READY_TIMEOUT = 180
EVENT_TIMEOUT = 30
SUBPROCESS_ENCODING = "utf-8"

USER_SCHEMA = json.loads((ROOT / "src" / "shared" / "schemas" / "user_schema.json").read_text())
ORDER_SCHEMA = json.loads((ROOT / "src" / "shared" / "schemas" / "order_schema.json").read_text())

DOCKER_CANDIDATES = [
    os.getenv("DOCKER_BIN"),
    shutil.which("docker"),
    shutil.which("docker.exe"),
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
]

ENV_KEYS = [
    "ENV_FILE",
    "FLASK_ENV",
    "P_VALUE",
    "RABBITMQ_HOST",
    "RABBITMQ_PORT",
    "RABBITMQ_USER",
    "RABBITMQ_PASSWORD",
    "RABBITMQ_QUEUE_NAME",
    "RABBITMQ_USER_USER",
    "RABBITMQ_USER_PASSWORD",
    "RABBITMQ_ORDER_USER",
    "RABBITMQ_ORDER_PASSWORD",
    "DATABASE_NAME",
    "MONGO_USERNAME",
    "MONGO_PASSWORD",
    "MONGO_URI",
]


def load_test_env() -> dict[str, str]:
    return {key: value for key, value in dotenv_values(TEST_ENV_FILE).items() if value is not None}


BASE_TEST_ENV = load_test_env()


def write_test_env(**overrides: str) -> dict[str, str]:
    values = BASE_TEST_ENV.copy()
    values.update({key: str(value) for key, value in overrides.items()})
    values["ENV_FILE"] = "tests/.env.integration"
    content = "\n".join(f"{key}={values[key]}" for key in ENV_KEYS) + "\n"
    TEST_ENV_FILE.write_text(content, encoding="utf-8")
    return values


def locate_docker_command() -> list[str] | None:
    for candidate in DOCKER_CANDIDATES:
        if candidate and Path(candidate).exists():
            return [candidate]
    return None


def run_compose(docker_command: list[str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = docker_command + [
        "compose",
        "--env-file",
        str(TEST_ENV_FILE),
        "-p",
        PROJECT_NAME,
        "-f",
        str(COMPOSE_FILE),
        *args,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            "Docker Compose command failed:\n"
            f"Command: {' '.join(command)}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )
    return completed


def wait_for_http_ready(
    url: str,
    expected_status: int | tuple[int, ...] = 200,
    timeout: int = READY_TIMEOUT,
) -> None:
    accepted_statuses = (
        (expected_status,) if isinstance(expected_status, int) else expected_status
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code in accepted_statuses:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"Service at {url} was not ready within {timeout} seconds")


def collect_compose_diagnostics(docker_command: list[str]) -> str:
    ps_result = run_compose(docker_command, "ps", check=False)
    kong_logs = run_compose(docker_command, "logs", "--no-color", "kong", check=False)
    return (
        "docker compose ps:\n"
        f"{ps_result.stdout or ps_result.stderr}\n\n"
        "kong logs:\n"
        f"{kong_logs.stdout or kong_logs.stderr}"
    )


def wait_for_stack_ready(docker_command: list[str]) -> None:
    try:
        wait_for_http_ready(f"{ADMIN_BASE_URL}/status")
    except TimeoutError as exc:
        diagnostics = collect_compose_diagnostics(docker_command)
        raise TimeoutError(f"{exc}\n\n{diagnostics}") from exc
    wait_for_http_ready(f"{API_BASE_URL}/orders?status=under%20process")


def eventually(assertion: Any, timeout: int = EVENT_TIMEOUT, interval: float = 1.0) -> None:
    deadline = time.time() + timeout
    last_error: AssertionError | None = None
    while time.time() < deadline:
        try:
            assertion()
            return
        except AssertionError as exc:
            last_error = exc
            time.sleep(interval)
    if last_error is None:
        raise AssertionError("Condition was not satisfied before timeout")
    raise last_error


def assert_schema(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = Draft7Validator(schema, format_checker=Draft7Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(payload), key=lambda item: item.path)
    assert not errors, "; ".join(error.message for error in errors)


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def build_user_payload(label: str) -> dict[str, Any]:
    return {
        "firstName": f"Integration-{label}",
        "lastName": "Tester",
        "emails": [f"{label}@example.com"],
        "deliveryAddress": {
            "street": f"{label}-street",
            "city": "Montreal",
            "state": "QC",
            "postalCode": "H1H1H1",
            "country": "Canada",
        },
    }


def build_order_payload(user: dict[str, Any], label: str) -> dict[str, Any]:
    return {
        "userId": user["userId"],
        "items": [
            {
                "itemId": f"item-{label}",
                "quantity": 2,
                "price": 19.99,
            }
        ],
        "userEmails": user["emails"],
        "deliveryAddress": user["deliveryAddress"],
        "orderStatus": "under process",
    }


def create_user_via_gateway(payload: dict[str, Any]) -> requests.Response:
    return requests.post(f"{API_BASE_URL}/users/", json=payload, timeout=REQUEST_TIMEOUT)


def get_user_via_gateway(user_id: str) -> requests.Response:
    return requests.get(f"{API_BASE_URL}/users/{user_id}", timeout=REQUEST_TIMEOUT)


def create_order_via_gateway(payload: dict[str, Any]) -> requests.Response:
    return requests.post(f"{API_BASE_URL}/orders/", json=payload, timeout=REQUEST_TIMEOUT)


def update_user_via_gateway(user_id: str, payload: dict[str, Any]) -> requests.Response:
    return requests.put(f"{API_BASE_URL}/users/{user_id}", json=payload, timeout=REQUEST_TIMEOUT)


def reconfigure_gateway(docker_command: list[str], p_value: str) -> None:
    write_test_env(P_VALUE=p_value)
    run_compose(docker_command, "up", "-d", "--force-recreate", "kong")
    wait_for_stack_ready(docker_command)


@pytest.fixture(scope="session")
def docker_command() -> list[str]:
    command = locate_docker_command()
    if command is None:
        pytest.skip("Docker is required for this integration suite but was not found.")
    version_check = subprocess.run(
        command + ["compose", "version"],
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors="replace",
        capture_output=True,
        check=False,
    )
    if version_check.returncode != 0:
        pytest.skip("Docker Compose is required for this integration suite.")
    daemon_check = subprocess.run(
        command + ["info"],
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors="replace",
        capture_output=True,
        check=False,
    )
    if daemon_check.returncode != 0:
        pytest.skip("Docker daemon is required for this integration suite.")
    return command


@pytest.fixture(scope="session", autouse=True)
def docker_stack(docker_command: list[str]) -> None:
    write_test_env(P_VALUE="1")
    run_compose(docker_command, "down", "-v", "--remove-orphans", check=False)
    run_compose(docker_command, "up", "--build", "-d")
    wait_for_stack_ready(docker_command)
    yield
    run_compose(docker_command, "down", "-v", "--remove-orphans", check=False)


def find_order_by_id(order_id: str, status: str = "under process") -> dict[str, Any]:
    response = requests.get(
        f"{API_BASE_URL}/orders",
        params={"status": status},
        timeout=REQUEST_TIMEOUT,
    )
    assert response.status_code == 200, response.text
    for order in response.json():
        if order["orderId"] == order_id:
            return order
    raise AssertionError(f"Order {order_id} not found in {status!r} orders")


def test_tc01_user_creation_and_retrieval() -> None:
    label = f"tc01-{unique_suffix()}"
    payload = build_user_payload(label)

    create_response = create_user_via_gateway(payload)
    assert create_response.status_code == 201, create_response.text
    created_user = create_response.json()
    assert_schema(created_user, USER_SCHEMA)

    get_response = get_user_via_gateway(created_user["userId"])
    assert get_response.status_code == 200, get_response.text
    retrieved_user = get_response.json()
    assert_schema(retrieved_user, USER_SCHEMA)

    assert retrieved_user["userId"] == created_user["userId"]
    assert retrieved_user["emails"] == payload["emails"]
    assert retrieved_user["deliveryAddress"] == payload["deliveryAddress"]


def test_tc02_order_creation_with_existing_user() -> None:
    label = f"tc02-{unique_suffix()}"
    user_response = create_user_via_gateway(build_user_payload(label))
    assert user_response.status_code == 201, user_response.text
    created_user = user_response.json()

    order_payload = build_order_payload(created_user, label)
    order_response = create_order_via_gateway(order_payload)
    assert order_response.status_code == 201, order_response.text
    created_order = order_response.json()
    assert_schema(created_order, ORDER_SCHEMA)

    assert created_order["userId"] == created_user["userId"]
    assert created_order["userEmails"] == created_user["emails"]
    assert created_order["deliveryAddress"] == created_user["deliveryAddress"]

    listed_order = find_order_by_id(created_order["orderId"])
    assert listed_order["userId"] == created_user["userId"]
    assert listed_order["userEmails"] == created_user["emails"]
    assert listed_order["deliveryAddress"] == created_user["deliveryAddress"]


def test_tc03_event_driven_user_update_propagation(
    docker_command: list[str],
) -> None:
    reconfigure_gateway(docker_command, "0")

    label = f"tc03-{unique_suffix()}"
    user_response = create_user_via_gateway(build_user_payload(label))
    assert user_response.status_code == 201, user_response.text
    created_user = user_response.json()

    order_response = create_order_via_gateway(build_order_payload(created_user, label))
    assert order_response.status_code == 201, order_response.text
    created_order = order_response.json()

    updated_details = {
        "emails": [f"updated-{label}@example.com"],
        "deliveryAddress": {
            "street": "updated-street",
            "city": "Toronto",
            "state": "ON",
            "postalCode": "M5V2T6",
            "country": "Canada",
        },
    }
    update_response = update_user_via_gateway(created_user["userId"], updated_details)
    assert update_response.status_code == 200, update_response.text

    def order_was_synchronized() -> None:
        synchronized_order = find_order_by_id(created_order["orderId"])
        assert synchronized_order["userEmails"] == updated_details["emails"]
        assert synchronized_order["deliveryAddress"] == updated_details["deliveryAddress"]

    eventually(order_was_synchronized)


def test_tc04_api_gateway_routing(
    docker_command: list[str],
) -> None:
    reconfigure_gateway(docker_command, "1")
    v1_response = create_user_via_gateway(build_user_payload(f"tc04-v1-{unique_suffix()}"))
    assert v1_response.status_code == 201, v1_response.text
    v1_user = v1_response.json()
    assert not v1_user.get("createdAt")
    assert not v1_user.get("updatedAt")

    reconfigure_gateway(docker_command, "0")
    v2_response = create_user_via_gateway(build_user_payload(f"tc04-v2-{unique_suffix()}"))
    assert v2_response.status_code == 201, v2_response.text
    v2_user = v2_response.json()
    assert v2_user.get("createdAt")
    assert v2_user.get("updatedAt")

    reconfigure_gateway(docker_command, "0.5")
    split_phase_users: list[dict[str, Any]] = []
    for _ in range(20):
        split_response = create_user_via_gateway(build_user_payload(f"tc04-split-{unique_suffix()}"))
        assert split_response.status_code == 201, split_response.text
        split_phase_users.append(split_response.json())

    timestamped_users = 0
    untimestamped_users = 0
    for user in split_phase_users:
        if user.get("createdAt") and user.get("updatedAt"):
            timestamped_users += 1
        else:
            untimestamped_users += 1

    assert timestamped_users > 0
    assert untimestamped_users > 0
