#!/usr/bin/env python3
"""Release proof #2: two generated apps for different passions look and are built differently.

Compiles the two structurally most distant goldens, opens both in a real
browser, and measures how far apart they are. Same spec chain, two different
practices, so a person should be able to tell them apart at a glance and a
screen reader should find a different structure underneath.

    python scripts/foundry_difference_gate.py
    python scripts/foundry_difference_gate.py --json
    python scripts/foundry_difference_gate.py --a sourdough-lab --b card-collector

Measured, with the thresholds this gate holds:

  topology            the two apps declare different `data-topology` values
  region_kinds        the sets of rendered region kinds are not the same, and
                      neither is a subset of the other
  landmarks           at least 3 of the counted landmark tags differ
  token_distance      >= 15 on a 0-100 scale over the two accent tokens, with
                      no more than 2 of the 6 palette tokens byte-identical and
                      two different type stacks
  screenshot_desktop  >= 25 percent of pixels differ at 1280x900
  screenshot_phone    >= 25 percent of pixels differ at 390x844
  axe                 zero serious or critical violations on both
  overflow            no horizontal scroll at 320px on either

Thresholds are here and nowhere else. Raising one to make a run pass is not a
fix, and neither is dropping an axis.

Today this gate is RED on purpose. The compiled apps share a DOM frame: no
`data-region-kind` attributes reach the markup and only one landmark tag count
differs between two very different practices. Lane B's compiler work is what
turns those rows green, and the failure output names exactly what is missing.
Palette, type stack, topology, screenshots and the accessibility floors already
pass.

Needs a browser: `cd app && npx playwright install chromium` once.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "tests" / "e2e-foundry" / "difference_probe.mjs"

if str(REPO_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "core"))

DEFAULT_A = "sourdough-lab"
DEFAULT_B = "japanese-study-coach"

THRESHOLDS: dict[str, float] = {
    "landmarks_differing": 3,
    "token_distance": 15.0,
    "screenshot_desktop": 25.0,
    "screenshot_phone": 25.0,
}

TOKEN_KEYS = ("background", "surface", "ink", "accent", "accentAlt", "border")
# More than this many byte-identical tokens means one palette wearing two names.
MAX_IDENTICAL_TOKENS = 2


# --------------------------------------------------------------------------
# PNG comparison, written out here so the gate adds no dependency.
# --------------------------------------------------------------------------


def read_png(path: Path) -> tuple[int, int, bytes]:
    """Return (width, height, RGBA bytes) for a non-interlaced 8-bit PNG."""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    offset = 8
    header: tuple[int, int, int, int, int, int, int] | None = None
    body = bytearray()
    palette = b""
    while offset < len(raw):
        (length,) = struct.unpack(">I", raw[offset : offset + 4])
        kind = raw[offset + 4 : offset + 8]
        payload = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"IDAT":
            body += payload
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path} has no header")
    width, height, depth, colour, _compression, _filter, interlace = header
    if depth != 8 or interlace != 0:
        raise ValueError(f"{path}: only 8-bit non-interlaced PNGs are compared")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    data = zlib.decompress(bytes(body))
    stride = width * channels
    out = bytearray()
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = data[position]
        position += 1
        line = bytearray(data[position : position + stride])
        position += stride
        _unfilter(filter_type, line, previous, channels)
        out += line
        previous = line
    return width, height, _to_rgba(bytes(out), width, height, channels, colour, palette)


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, channels: int) -> None:
    if filter_type == 0:
        return
    for index in range(len(line)):
        left = line[index - channels] if index >= channels else 0
        up = previous[index]
        upper_left = previous[index - channels] if index >= channels else 0
        if filter_type == 1:
            line[index] = (line[index] + left) & 0xFF
        elif filter_type == 2:
            line[index] = (line[index] + up) & 0xFF
        elif filter_type == 3:
            line[index] = (line[index] + (left + up) // 2) & 0xFF
        elif filter_type == 4:
            line[index] = (line[index] + _paeth(left, up, upper_left)) & 0xFF
        else:
            raise ValueError(f"unknown PNG filter {filter_type}")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _to_rgba(
    data: bytes, width: int, height: int, channels: int, colour: int, palette: bytes
) -> bytes:
    if colour == 6:
        return data
    out = bytearray()
    for index in range(width * height):
        chunk = data[index * channels : (index + 1) * channels]
        if colour == 2:
            out += chunk + b"\xff"
        elif colour == 0:
            out += bytes(chunk) * 3 + b"\xff"
        elif colour == 4:
            out += bytes(chunk[:1]) * 3 + chunk[1:2]
        elif colour == 3:
            base = chunk[0] * 3
            out += palette[base : base + 3] + b"\xff"
    return bytes(out)


def screenshot_difference(left: Path, right: Path, *, tolerance: int = 12) -> float:
    """Percentage of pixels that differ, ignoring imperceptible shifts."""
    lw, lh, lp = read_png(left)
    rw, rh, rp = read_png(right)
    if (lw, lh) != (rw, rh):
        return 100.0
    total = lw * lh
    if total == 0:
        return 0.0
    differing = 0
    for index in range(0, total * 4, 4):
        delta = (
            abs(lp[index] - rp[index])
            + abs(lp[index + 1] - rp[index + 1])
            + abs(lp[index + 2] - rp[index + 2])
        )
        if delta > tolerance:
            differing += 1
    return 100.0 * differing / total


# --------------------------------------------------------------------------
# Token distance
# --------------------------------------------------------------------------


def parse_colour(value: str) -> tuple[int, int, int] | None:
    text = value.strip().lower()
    match = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    match = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", text)
    if match:
        return tuple(int(float(part)) for part in match.groups())  # type: ignore[return-value]
    return None


def colour_gap(left: str, right: str) -> float | None:
    """0 for the same colour, 100 for black against white."""
    a, b = parse_colour(left), parse_colour(right)
    if a is None or b is None:
        return None
    return 100.0 * sum(abs(x - y) for x, y in zip(a, b, strict=True)) / 765.0


def token_distance(left: dict[str, str], right: dict[str, str]) -> tuple[float, list[str]]:
    """How far apart two palettes read, scored on the accents.

    Measured on the goldens rather than guessed: two visual worlds that a
    person calls obviously different (the sourdough bench and the study coach)
    sit 23.6 apart on the accents and under 5 apart on background, surface,
    ink and border, because both are warm-paper worlds. Averaging all six
    tokens buries the signal in neutrals that are supposed to be quiet, so the
    score is the accent pair, and the neutrals are checked separately for being
    byte-identical, which is what "the same palette twice" actually looks like.
    """
    notes: list[str] = []
    accents: list[float] = []
    for key in ("accent", "accentAlt"):
        gap = colour_gap(left.get(key, ""), right.get(key, ""))
        if gap is None:
            notes.append(f"token {key} is not a colour this gate can read")
            accents.append(0.0)
        else:
            accents.append(gap)

    identical = [
        key for key in TOKEN_KEYS if colour_gap(left.get(key, ""), right.get(key, "")) == 0.0
    ]
    if len(identical) > MAX_IDENTICAL_TOKENS:
        notes.append(
            f"{len(identical)} of {len(TOKEN_KEYS)} palette tokens are byte-identical "
            f"({', '.join(identical)}); the two apps are painted from one palette"
        )

    stack_left = left.get("fontFamily", "").strip().lower()
    stack_right = right.get("fontFamily", "").strip().lower()
    if stack_left and stack_left == stack_right:
        notes.append(f"both apps use the same type stack ({stack_left})")

    score = sum(accents) / len(accents) if accents else 0.0
    if notes:
        score = 0.0
    return score, notes


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    passed: bool
    measured: str
    needed: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "measured": self.measured,
            "needed": self.needed,
            "notes": self.notes,
        }


def compile_goldens(names: tuple[str, str], workdir: Path) -> dict[str, Path]:
    from domain_foundry_core.foundry.compiler import FoundryCompiler
    from domain_foundry_core.foundry.loader import DEFAULT_GOLDENS, load_foundry_spec

    built: dict[str, Path] = {}
    for name in names:
        spec_path = DEFAULT_GOLDENS / f"{name}.foundry.yaml"
        if not spec_path.is_file():
            raise SystemExit(
                f"there is no golden spec named {name}. "
                f"Available: {', '.join(sorted(p.name.split('.')[0] for p in DEFAULT_GOLDENS.glob('*.foundry.yaml')))}"
            )
        artifact = FoundryCompiler().compile(load_foundry_spec(spec_path), workdir / name)
        built[name] = artifact.app
    return built


def run_probe(pages: dict[str, Path], out_dir: Path) -> dict[str, Any]:
    if not (REPO_ROOT / "app" / "node_modules" / "@playwright").is_dir():
        raise SystemExit(
            "The difference gate needs a browser and it is not installed.\n"
            "Run: cd app && npm ci && npx playwright install chromium"
        )
    job = json.dumps(
        {
            "outDir": str(out_dir),
            "pages": [{"id": name, "path": str(path)} for name, path in pages.items()],
        }
    )
    result = subprocess.run(
        ["node", str(PROBE), job],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"The browser probe did not finish.\n{result.stdout.strip()}\n{result.stderr.strip()}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def evaluate(probe: dict[str, Any]) -> list[Check]:
    left, right = probe["pages"][0], probe["pages"][1]
    ls, rs = left["structure"], right["structure"]
    checks: list[Check] = []

    topologies = (ls.get("topology"), rs.get("topology"))
    checks.append(
        Check(
            "topology",
            passed=all(topologies) and topologies[0] != topologies[1],
            measured=f"{topologies[0]!r} against {topologies[1]!r}",
            needed="two different, non-empty data-topology values",
            notes=(
                []
                if all(topologies)
                else [
                    "Missing: the compiler does not write data-topology on <body>. "
                    "The stylesheet already has rules for it "
                    "(core/domain_foundry_core/foundry/compiler.py, Lane B), "
                    "but nothing sets the attribute, so every app gets the same frame."
                ]
            ),
        )
    )

    left_kinds, right_kinds = set(ls.get("regionKinds") or []), set(rs.get("regionKinds") or [])
    kinds_differ = bool(left_kinds) and bool(right_kinds) and left_kinds != right_kinds
    checks.append(
        Check(
            "region_kinds",
            passed=kinds_differ and not (left_kinds <= right_kinds or right_kinds <= left_kinds),
            measured=f"{sorted(left_kinds)} against {sorted(right_kinds)}",
            needed="two sets that differ and neither contains the other",
            notes=(
                []
                if left_kinds and right_kinds
                else [
                    "Missing: the compiled app carries no data-region-kind attributes, "
                    "so the spec's region kinds are not visible in the DOM "
                    "(core/domain_foundry_core/foundry/compiler.py, Lane B)."
                ]
            ),
        )
    )

    differing = [
        key for key in ls["landmarks"] if ls["landmarks"].get(key) != rs["landmarks"].get(key)
    ]
    checks.append(
        Check(
            "landmarks",
            passed=len(differing) >= THRESHOLDS["landmarks_differing"],
            measured=f"{len(differing)} differ: {', '.join(differing) or 'none'}",
            needed=f"at least {int(THRESHOLDS['landmarks_differing'])} differ",
        )
    )

    distance, token_notes = token_distance(
        {**ls["tokens"], "fontFamily": ls["fontFamily"]},
        {**rs["tokens"], "fontFamily": rs["fontFamily"]},
    )
    checks.append(
        Check(
            "token_distance",
            passed=distance >= THRESHOLDS["token_distance"],
            measured=f"{distance:.1f}",
            needed=f"at least {THRESHOLDS['token_distance']:.0f}",
            notes=token_notes,
        )
    )

    for label, key in (("screenshot_desktop", "desktopShot"), ("screenshot_phone", "phoneShot")):
        percent = screenshot_difference(Path(left[key]), Path(right[key]))
        checks.append(
            Check(
                label,
                passed=percent >= THRESHOLDS[label],
                measured=f"{percent:.1f} percent of pixels",
                needed=f"at least {THRESHOLDS[label]:.0f} percent",
            )
        )

    violations = [
        f"{page['id']}: {item['id']} ({item['impact']}, {item['nodes']} nodes)"
        for page in (left, right)
        for item in page["axeViolations"]
    ]
    checks.append(
        Check(
            "axe",
            passed=not violations,
            measured=f"{len(violations)} serious or critical violations",
            needed="zero",
            notes=violations,
        )
    )

    overflowing = [page["id"] for page in (left, right) if page["overflowAt320"]]
    checks.append(
        Check(
            "overflow",
            passed=not overflowing,
            measured=f"{len(overflowing)} apps scroll sideways at 320px",
            needed="zero",
            notes=overflowing,
        )
    )
    return checks


def render(checks: list[Check], names: tuple[str, str]) -> str:
    lines = [f"difference gate: {names[0]} against {names[1]}"]
    for check in checks:
        mark = "ok  " if check.passed else "FAIL"
        lines.append(f"  {mark} {check.name:<20} {check.measured}  (needs {check.needed})")
        lines.extend(f"       {note}" for note in check.notes)
    lines.append("")
    lines.append("PASS" if all(item.passed for item in checks) else "FAIL")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", default=DEFAULT_A, help="First golden spec id")
    parser.add_argument("--b", default=DEFAULT_B, help="Second golden spec id")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a report")
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=None,
        help="Keep the built apps and screenshots in this directory",
    )
    args = parser.parse_args(argv)

    names = (args.a, args.b)
    workdir = args.artifacts or Path(tempfile.mkdtemp(prefix="difference-gate-"))
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        pages = compile_goldens(names, workdir / "apps")
        probe = run_probe(pages, workdir / "shots")
        checks = evaluate(probe)
    finally:
        if args.artifacts is None:
            shutil.rmtree(workdir, ignore_errors=True)

    if args.json:
        print(
            json.dumps(
                {
                    "pair": list(names),
                    "passed": all(item.passed for item in checks),
                    "checks": [item.as_dict() for item in checks],
                },
                indent=2,
            )
        )
    else:
        print(render(checks, names))
    return 0 if all(item.passed for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
