import importlib.util
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "variant_workspaces"
HOST_ROOT = Path(os.environ.get(
    "MANUSKRIPT_ROOT",
    str(ROOT.parent / "manuskript"),
)).resolve()

if (HOST_ROOT / "manuskript").is_dir():
    sys.path.insert(0, str(HOST_ROOT))


if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
