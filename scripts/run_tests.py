"""Minimal zero-dependency test runner.

Discovers tests/test_*.py, runs every test_* function, supports the tmp_path
fixture. Use real pytest when available (`pip install -e .[dev] && pytest`);
this exists so the suite can run in environments without pytest.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    passed, failed = 0, []
    for test_file in sorted((ROOT / "tests").glob("test_*.py")):
        mod = load_module(test_file)
        for name, fn in sorted(vars(mod).items()):
            if not (name.startswith("test_") and callable(fn)):
                continue
            kwargs = {}
            if "tmp_path" in inspect.signature(fn).parameters:
                tmp = tempfile.TemporaryDirectory()
                kwargs["tmp_path"] = Path(tmp.name)
            try:
                fn(**kwargs)
                passed += 1
                print(f"PASS {test_file.name}::{name}")
            except Exception:
                failed.append(f"{test_file.name}::{name}")
                print(f"FAIL {test_file.name}::{name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
