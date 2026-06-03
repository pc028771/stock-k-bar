"""Playbook and Light YAML loader for the Scenario Advisor layer.

Public API
----------
- ``load_playbooks(dirs)`` — load all *.yaml from dirs, return dict keyed by pattern
- ``load_lights(dirs)`` — load all *.yaml from dirs, return dict keyed by light_id
- ``LoaderError`` — raised for file-level validation failures (wraps Pydantic errors)

Design notes
------------
- Uses PyYAML ``safe_load`` only (no arbitrary Python constructors)
- Pydantic ValidationError is caught and re-raised as LoaderError with filename + field path
- Fail-loud on duplicates: duplicate light_id or (pattern, setup.name) pair raises ValueError
- Empty or nonexistent directories return empty dicts — no exception raised
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ._schema import Light, Playbook


class LoaderError(Exception):
    """Raised when a YAML file fails schema validation.

    Always includes the source filename and field path in the message so
    developers can immediately identify and fix the offending file.
    """


def _iter_yaml_files(dirs: list[Path]):
    """Yield all *.yaml files found in the given directories."""
    for d in dirs:
        if not d.exists() or not d.is_dir():
            continue
        yield from sorted(d.glob("*.yaml"))


def _load_raw(path: Path) -> Any:
    """Load a YAML file with safe_load. Returns the parsed object."""
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _format_validation_error(exc: ValidationError, filepath: Path) -> str:
    """Format a Pydantic ValidationError into a human-readable message with filename."""
    lines = [f"Schema validation failed in '{filepath.name}':"]
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"]) if err["loc"] else "(root)"
        msg = err["msg"]
        lines.append(f"  field '{loc}': {msg}")
    return "\n".join(lines)


def load_playbooks(dirs: list[Path]) -> dict[str, list[Playbook]]:
    """Load all *.yaml playbook files from the given directories.

    Parameters
    ----------
    dirs:
        List of directories to scan for ``*.yaml`` files.  Nonexistent or
        empty directories are silently skipped.

    Returns
    -------
    dict[str, list[Playbook]]
        Mapping from ``pattern`` → list of ``Playbook`` objects.
        Multiple setups per pattern are allowed; duplicate (pattern, setup.name)
        pairs across files raise ``ValueError``.

    Raises
    ------
    LoaderError
        If any YAML file fails Pydantic validation (includes filename + field path).
    ValueError
        If a duplicate (pattern, setup.name) pair is detected.
    """
    result: dict[str, list[Playbook]] = {}
    seen_keys: dict[tuple[str, str], Path] = {}  # (pattern, setup.name) → source file

    for filepath in _iter_yaml_files(dirs):
        raw = _load_raw(filepath)
        try:
            playbook = Playbook.model_validate(raw)
        except ValidationError as exc:
            raise LoaderError(_format_validation_error(exc, filepath)) from exc

        key = (playbook.pattern, playbook.setup.name)
        if key in seen_keys:
            raise ValueError(
                f"Duplicate (pattern, setup.name) = {key!r} found in "
                f"'{filepath.name}' (first seen in '{seen_keys[key].name}')"
            )
        seen_keys[key] = filepath

        result.setdefault(playbook.pattern, []).append(playbook)

    return result


def load_lights(dirs: list[Path]) -> dict[str, Light]:
    """Load all *.yaml light files from the given directories.

    Parameters
    ----------
    dirs:
        List of directories to scan for ``*.yaml`` files.  Nonexistent or
        empty directories are silently skipped.

    Returns
    -------
    dict[str, Light]
        Mapping from ``light_id`` → ``Light`` object.

    Raises
    ------
    LoaderError
        If any YAML file fails Pydantic validation (includes filename + field path).
    ValueError
        If a duplicate ``light_id`` is detected across files.
    """
    result: dict[str, Light] = {}
    seen_ids: dict[str, Path] = {}  # light_id → source file

    for filepath in _iter_yaml_files(dirs):
        raw = _load_raw(filepath)
        try:
            light = Light.model_validate(raw)
        except ValidationError as exc:
            raise LoaderError(_format_validation_error(exc, filepath)) from exc

        if light.light_id in seen_ids:
            raise ValueError(
                f"Duplicate light_id '{light.light_id}' found in "
                f"'{filepath.name}' (first seen in '{seen_ids[light.light_id].name}')"
            )
        seen_ids[light.light_id] = filepath
        result[light.light_id] = light

    return result
