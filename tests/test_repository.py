import pytest

from variant_workspaces.model import (
    VariantDataError,
    VariantGroup,
    VariantMember,
    VariantState,
)
from variant_workspaces.repository import VariantRepository


class MemoryFiles:
    def __init__(self):
        self.values = {}

    def read(self, path, default=None):
        return self.values.get(path, default)

    def write(self, path, value):
        changed = self.values.get(path) != value
        self.values[path] = value
        return changed


def test_repository_round_trip_is_namespaced_and_deterministic():
    files = MemoryFiles()
    repository = VariantRepository(files)
    member = VariantMember.create("1", "Original")
    group = VariantGroup.create("Scene", (member,))
    state = VariantState((group,), group.id)

    assert repository.save_state(state)
    assert not repository.save_state(state)
    assert repository.load_state() == state
    assert set(files.values) == {"variant-groups.json"}


def test_invalid_json_is_not_silently_overwritten():
    files = MemoryFiles()
    files.values["variant-groups.json"] = "{broken"

    with pytest.raises(VariantDataError, match="invalid JSON"):
        VariantRepository(files).load_state()

    assert files.values["variant-groups.json"] == "{broken"
