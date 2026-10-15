"""Runtime validation for offsets.schema.json (no external dependency)."""
import re

TYPE_FORMATS = {"int8": "b", "uint8": "B", "int16": "h", "uint16": "H",
                "int32": "i", "uint32": "I", "float32": "f", "float64": "d"}
ENTRY_KEYS = {"module", "base_rva", "steps", "terminal", "type", "verified", "note", "source"}


def validate_offsets(data):
    if not isinstance(data, dict) or set(data) != {"$schema", "schema_version", "entries"}:
        raise ValueError("offsets: expected $schema, schema_version and entries")
    if data["$schema"] != "offsets.schema.json" or type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise ValueError("offsets: unsupported schema/version")
    if not isinstance(data["entries"], dict):
        raise ValueError("offsets.entries must be an object")
    for name, entry in data["entries"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", name):
            raise ValueError(f"Invalid entry name: {name}")
        if (not isinstance(entry, dict) or not ENTRY_KEYS <= set(entry)
                or set(entry) - ENTRY_KEYS - {"mask", "shift", "deref"}):
            raise ValueError(f"{name}: required {sorted(ENTRY_KEYS)}; optional mask, shift, deref")
        for key in ("module", "note"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise ValueError(f"{name}.{key}: nonempty string required")
        if any(c in entry["module"] for c in "/\\"):
            raise ValueError(f"{name}.module: exact module filename required, not a path")
        if entry["base_rva"] is not None and (type(entry["base_rva"]) is not int or not 0 <= entry["base_rva"] <= 0xFFFFFFFF):
            raise ValueError(f"{name}.base_rva: unsigned 32-bit integer required")
        if entry["terminal"] is not None and type(entry["terminal"]) is not int:
            raise ValueError(f"{name}.terminal: integer required")
        steps = entry["steps"]
        if steps is not None and (not isinstance(steps, list) or len(steps) > 16 or any(v is not None and type(v) is not int for v in steps)):
            raise ValueError(f"{name}.steps: at most 16 integer offsets required")
        if not isinstance(entry["type"], str) or entry["type"] not in TYPE_FORMATS:
            raise ValueError(f"{name}.type: unsupported scalar type")
        if type(entry["verified"]) is not bool:
            raise ValueError(f"{name}.verified: boolean required")
        if entry["source"] not in ("assumed", "verified_ce", "reversed_disasm"):
            raise ValueError(f"{name}.source: expected assumed, verified_ce or reversed_disasm")
        if "deref" in entry and type(entry["deref"]) is not bool:
            raise ValueError(f"{name}.deref: boolean required")
        if "shift" in entry and "mask" not in entry:
            raise ValueError(f"{name}.shift requires mask")
        if "mask" in entry:
            if entry["type"].startswith("float"):
                raise ValueError(f"{name}.mask requires an integer field type")
            if type(entry["mask"]) is not int or not 0 <= entry["mask"] <= 0xFFFFFFFF:
                raise ValueError(f"{name}.mask: unsigned 32-bit integer required")
            shift = entry.get("shift", 0)
            if type(shift) is not int or not 0 <= shift <= 31:
                raise ValueError(f"{name}.shift: integer from 0 through 31 required")
        if entry["verified"] and (entry["base_rva"] is None or entry["terminal"] is None
                                  or steps is None or any(v is None for v in steps)):
            raise ValueError(f"{name}: verified entry cannot contain uncalibrated offsets")
    return data
