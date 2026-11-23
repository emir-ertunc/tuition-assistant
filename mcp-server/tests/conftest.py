from pathlib import Path

import pytest

from indexer import PolicyIndex

POLICY_FILE = Path(__file__).resolve().parent.parent / "data" / "University_Tuition_Policies.md"


@pytest.fixture(scope="session")
def index() -> PolicyIndex:
    return PolicyIndex.from_file(POLICY_FILE)


@pytest.fixture
def anyio_backend():
    return "asyncio"
