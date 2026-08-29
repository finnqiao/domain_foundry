"""Read colours and type off a reference file you already have.

`vibe` takes a picture or a page you like and reads a palette out of it. It all
happens on your machine with what Python already ships: no image library, no
network call, nothing uploaded.

What it can read:

- **PNG pictures.** Eight bits a channel, not interlaced, which is what a
  screenshot is. JPEG is not readable here, because decoding one honestly
  would mean shipping a decoder, so save the picture as a PNG first.
- **HTML and CSS files.** The colours written in them, and the font families
  they ask for.

What comes out is a proposal. Nothing is saved until you approve it, either by
pressing Save on the review page or by running `tokens`.
"""

from __future__ import annotations

import colorsys
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# How many pixels we look at. A screenshot has more than we need, and reading
# every one of a large picture is slow for no better answer.
_MAX_SAMPLES = 40_000


class VibeError(ValueError):
    """A reference we cannot read, with a sentence a person can act on."""


@dataclass(frozen=True)
class VibeReading:
    """What one reference file said."""

    source: str
    kind: str
    colours: tuple[str, ...]
    tokens: dict[str, str] = field(default_factory=dict)
    typography_stack: str | None = None
    note: str = ""


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _luminance(rgb: tuple[int, int, int]) -> float:
    red, green, blue = (channel / 255 for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _saturation(rgb: tuple[int, int, int]) -> float:
    red, green, blue = (channel / 255 for channel in rgb)
    return colorsys.rgb_to_hls(red, green, blue)[2]


def _mix(one: tuple[int, int, int], two: tuple[int, int, int], amount: float) -> str:
    return _hex(
        (
            round(one[0] + (two[0] - one[0]) * amount),
            round(one[1] + (two[1] - one[1]) * amount),
            round(one[2] + (two[2] - one[2]) * amount),
        )
    )


def tokens_from_colours(colours: list[str]) -> dict[str, str]:
    """Turn an ordered palette into the tokens a spec understands.

    The most used colour becomes the page behind everything. The colour
    furthest from it in brightness becomes the words. The most colourful one
    becomes the accent. `danger` is left alone on purpose: a warning colour
    should not be borrowed from a picture.
    """

    if not colours:
        return {}
    ordered = [value.upper() for value in colours]
    background = _rgb(ordered[0])
    rest = [_rgb(value) for value in ordered[1:]] or [background]
    text = max(rest, key=lambda item: abs(_luminance(item) - _luminance(background)))
    colourful = sorted(rest, key=_saturation, reverse=True)
    accent = next((item for item in colourful if item != text), text)
    accent_alt = next((item for item in colourful if item not in {text, accent}), accent)
    return {
        "background": _hex(background),
        "surface": _mix(background, text, 0.06),
        "text": _hex(text),
        "muted": _mix(text, background, 0.45),
        "accent": _hex(accent),
        "accent_alt": _hex(accent_alt),
        "border": _mix(background, text, 0.18),
        "focus": _hex(accent_alt),
    }


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------

_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _png_pixels(data: bytes) -> list[tuple[int, int, int]]:
    if not data.startswith(PNG_MAGIC):
        raise VibeError("That file does not start like a PNG.")
    offset = len(PNG_MAGIC)
    header: tuple[int, int, int, int, int, int, int] | None = None
    palette: list[tuple[int, int, int]] = []
    compressed = bytearray()
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [tuple(body[i : i + 3]) for i in range(0, len(body) - 2, 3)]  # type: ignore[misc]
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
    if header is None:
        raise VibeError("That PNG has no header chunk, so there is nothing to read.")
    width, height, depth, colour_type, _, _, interlace = header
    if depth != 8:
        raise VibeError(
            f"This PNG stores {depth} bits a channel. Save it again as an ordinary "
            "8 bit PNG and try once more."
        )
    if interlace != 0:
        raise VibeError(
            "This PNG is interlaced. Save it again without interlacing and try once more."
        )
    if colour_type not in _CHANNELS:
        raise VibeError(f"This PNG uses a colour type ({colour_type}) that cannot be read here.")
    if colour_type == 3 and not palette:
        raise VibeError("This PNG says it uses a palette but does not carry one.")
    channels = _CHANNELS[colour_type]
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise VibeError("This PNG is cut short, so its pixels cannot be read.")

    pixels: list[tuple[int, int, int]] = []
    previous = bytearray(stride)
    step = max(1, (width * height) // _MAX_SAMPLES)
    counter = 0
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        _unfilter(filter_type, line, previous, channels)
        for index in range(0, stride, channels):
            counter += 1
            if counter % step:
                continue
            if colour_type == 3:
                entry = line[index]
                if entry < len(palette):
                    pixels.append(palette[entry])
                continue
            if colour_type in (0, 4):
                grey = line[index]
                pixels.append((grey, grey, grey))
                continue
            if colour_type == 6 and line[index + 3] < 128:
                continue
            pixels.append((line[index], line[index + 1], line[index + 2]))
        previous = line
    if not pixels:
        raise VibeError("Every pixel in that PNG is see through, so there is no palette in it.")
    return pixels


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, channels: int) -> None:
    if filter_type == 0:
        return
    for index in range(len(line)):
        left = line[index - channels] if index >= channels else 0
        up = previous[index]
        up_left = previous[index - channels] if index >= channels else 0
        if filter_type == 1:
            line[index] = (line[index] + left) & 0xFF
        elif filter_type == 2:
            line[index] = (line[index] + up) & 0xFF
        elif filter_type == 3:
            line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:
            line[index] = (line[index] + _paeth(left, up, up_left)) & 0xFF
        else:
            raise VibeError(f"This PNG uses a row filter ({filter_type}) that is not part of PNG.")


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_corner = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_corner:
        return left
    if distance_up <= distance_corner:
        return up
    return up_left


def palette_from_pixels(pixels: list[tuple[int, int, int]], *, count: int = 6) -> list[str]:
    """Group near enough colours together and return the most used ones."""

    buckets: dict[tuple[int, int, int], list[int]] = {}
    for pixel in pixels:
        key = (pixel[0] >> 5, pixel[1] >> 5, pixel[2] >> 5)
        bucket = buckets.setdefault(key, [0, 0, 0, 0])
        bucket[0] += pixel[0]
        bucket[1] += pixel[1]
        bucket[2] += pixel[2]
        bucket[3] += 1
    ranked = sorted(buckets.values(), key=lambda bucket: bucket[3], reverse=True)
    return [
        _hex(
            (
                bucket[0] // bucket[3],
                bucket[1] // bucket[3],
                bucket[2] // bucket[3],
            )
        )
        for bucket in ranked[:count]
    ]


# ---------------------------------------------------------------------------
# HTML and CSS
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\b")
_RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
_FONT_RE = re.compile(r"font-family\s*:\s*([^;{}\"']+)", re.IGNORECASE)

_FAMILY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "mono_forward",
        ("mono", "menlo", "consolas", "courier", "jetbrains", "iosevka", "source code"),
    ),
    ("rounded_humanist", ("rounded", "nunito", "quicksand", "comfortaa", "varela", "baloo")),
    (
        "reading_serif",
        ("serif", "georgia", "times", "garamond", "charter", "iowan", "merriweather", "lora"),
    ),
    (
        "data_sans",
        ("sans", "helvetica", "arial", "inter", "roboto", "system-ui", "segoe", "ibm plex sans"),
    ),
)


def palette_from_markup(text: str, *, count: int = 6) -> list[str]:
    """Collect the colours a page or stylesheet writes down, most used first."""

    tally: dict[str, int] = {}
    order: list[str] = []
    for match in _HEX_RE.finditer(text):
        value = _hex(_rgb(match.group(0)))
        if value not in tally:
            order.append(value)
        tally[value] = tally.get(value, 0) + 1
    for match in _RGB_RE.finditer(text):
        channels = tuple(min(255, int(part)) for part in match.groups())
        value = _hex(channels)  # type: ignore[arg-type]
        if value not in tally:
            order.append(value)
        tally[value] = tally.get(value, 0) + 1
    first_seen = {value: index for index, value in enumerate(order)}
    order.sort(key=lambda value: (-tally[value], first_seen[value]))
    return order[:count]


def typography_from_markup(text: str) -> str | None:
    """Name the closest shipped type stack to what the page asks for."""

    for match in _FONT_RE.finditer(text):
        families = match.group(1).casefold()
        without_sans = families.replace("sans-serif", "sans")
        for stack, hints in _FAMILY_HINTS:
            if any(hint in without_sans for hint in hints):
                return stack
    return None


# ---------------------------------------------------------------------------
# The one door in
# ---------------------------------------------------------------------------


def read_reference(path: Path) -> VibeReading:
    """Read a palette, and where possible a type choice, off one local file."""

    if not path.exists():
        raise VibeError(f"There is no file at {path}.")
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        raise VibeError(
            "JPEG pictures cannot be read here. Open it and save it again as a PNG, "
            "then point at that."
        )
    if suffix == ".png" or path.read_bytes()[:8] == PNG_MAGIC:
        pixels = _png_pixels(path.read_bytes())
        colours = palette_from_pixels(pixels)
        return VibeReading(
            source=path.name,
            kind="png",
            colours=tuple(colours),
            tokens=tokens_from_colours(colours),
            note=(
                f"Read {len(colours)} colours out of {path.name} on this machine. "
                "The picture was not sent anywhere."
            ),
        )
    if suffix in {".html", ".htm", ".css", ".xhtml", ".svg"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        colours = palette_from_markup(text)
        if not colours:
            raise VibeError(
                f"{path.name} does not write any colours down, so there is nothing to read "
                "off it. Point at a file that sets colours, or a PNG screenshot of the page."
            )
        stack = typography_from_markup(text)
        told = f" It asks for type like {stack.replace('_', ' ')}." if stack else ""
        return VibeReading(
            source=path.name,
            kind="css" if suffix == ".css" else "html",
            colours=tuple(colours),
            tokens=tokens_from_colours(colours),
            typography_stack=stack,
            note=(
                f"Read {len(colours)} colours out of {path.name} on this machine.{told} "
                "The file was not sent anywhere."
            ),
        )
    raise VibeError(
        f"{path.name} is not a kind of reference that can be read here. Point at a PNG "
        "picture, an HTML page, or a CSS file that lives on your machine."
    )


__all__ = [
    "PNG_MAGIC",
    "VibeError",
    "VibeReading",
    "palette_from_markup",
    "palette_from_pixels",
    "read_reference",
    "tokens_from_colours",
    "typography_from_markup",
]
