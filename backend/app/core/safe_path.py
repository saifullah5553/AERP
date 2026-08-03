"""Guard against Windows device names, which turn a file read into a permanent hang.

CON, PRN, AUX, NUL, COM1-9 and LPT1-9 are devices on Windows, in *every* directory and with
*any* extension. So `company/CON.json` is not a file - it is the console. `Path.exists()`
returns True for it, and the read that follows blocks forever waiting for console input. With
stdin detached, as in any scheduled or background run, it never returns and never burns CPU:
the process just sits at 0% looking exactly like a deadlock.

This is not hypothetical. CON is a real US ticker (Concentra Group), and it wedged the quality
history job repeatedly - the run appeared to hang seconds after starting, survived being killed
and relaunched five times, and held the snapshot lock each time.

The snapshot is authored on Windows, so every per-symbol file path must go through here.
"""

from __future__ import annotations

from pathlib import Path

# Reserved in every directory, with or without an extension.
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def is_reserved(name: str) -> bool:
    """Would opening a file with this base name hit a Windows device?"""
    return name.split(".", 1)[0].strip().upper() in RESERVED_NAMES


def safe_file(directory: Path, name: str) -> Path | None:
    """`directory/name`, or None when reading it would block on a device.

    Returning None rather than raising keeps the caller's shape: these are per-symbol sweeps
    over thousands of names, and one unluckily-named ticker must skip, not stop the batch.
    """
    if is_reserved(name):
        return None
    return directory / name
