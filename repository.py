import json

from .model import (
    ComparisonState,
    VariantDataError,
    VariantState,
    comparison_from_dict,
    comparison_to_dict,
    state_from_dict,
    state_to_dict,
)


GROUPS_FILE = "variant-groups.json"
WORKSPACES_FILE = "comparison-workspaces.json"


class VariantRepository:
    """Persist portable domain data through Manuskript's plugin namespace."""

    def __init__(self, files):
        self.files = files

    def load_state(self):
        value = self._read_json(GROUPS_FILE, None)
        return VariantState() if value is None else state_from_dict(value)

    def save_state(self, state):
        return self._write_json(GROUPS_FILE, state_to_dict(state))

    def load_comparisons(self):
        value = self._read_json(WORKSPACES_FILE, {"workspaces": []})
        if not isinstance(value, dict):
            raise VariantDataError(
                "Comparison workspace data must be a JSON object."
            )
        states = tuple(
            comparison_from_dict(item)
            for item in value.get("workspaces", ())
        )
        return {state.group_id: state for state in states}

    def save_comparisons(self, comparisons):
        states = sorted(
            comparisons.values(),
            key=lambda state: state.group_id,
        )
        return self._write_json(
            WORKSPACES_FILE,
            {
                "schema_version": 1,
                "workspaces": [
                    comparison_to_dict(state) for state in states
                ],
            },
        )

    def comparison_for(self, group):
        comparisons = self.load_comparisons()
        return comparisons.get(
            group.id,
            ComparisonState(
                group_id=group.id,
                pane_order=tuple(member.id for member in group.members),
            ),
        )

    def _read_json(self, path, default):
        raw = self.files.read(path)
        if raw is None:
            return default
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise VariantDataError(
                    "{} is not UTF-8 text.".format(path)
                ) from error
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as error:
            raise VariantDataError(
                "{} contains invalid JSON: {}".format(path, error)
            ) from error

    def _write_json(self, path, value):
        return self.files.write(
            path,
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
        )
