"""Generate a square line-art portrait and convert it to pen-plotter SVG.

Run this script on the GB10, where ComfyUI is available on localhost:8188.
It deliberately produces an SVG made only from open stroked paths: no fills,
embedded raster images, masks, filters, or background rectangle.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import requests
from PIL import Image, ImageOps, ImageDraw


DEFAULT_PROMPT = (
    "Create a centered square head-and-shoulders line portrait of the person "
    "in the reference photograph. Preserve the person's recognizable facial "
    "proportions, hairstyle and expression. The generated image itself must "
    "contain thin black lines only on a completely white background. Use "
    "clean, sparse, continuous, uniform-width centerline strokes. Every facial "
    "feature must be represented by outline strokes only. Draw hair using only "
    "a few contour and strand lines. Draw each eyebrow only as one simple, "
    "thin outer outline of its overall shape, with a completely empty white interior. "
    "No individual eyebrow hairs, short dashes, interior strokes, hatching, "
    "shading, filled eyebrows, overlapping lines or repeated tracing. "
    "Draw pupils, nostrils and lips as thin contours, never as black shapes. "
    "Draw only the person: face, hair "
    "contours, neck, shoulders and one simple clothing neckline. No scenery "
    "and no objects from the original background. Absolutely no solid black "
    "areas, no filled shapes, no thick masses, no shading, no gray, no color, "
    "no hatching, no cross-hatching, no stippling, no shadows, no gradients, "
    "no text and no border. Minimal centerline vector art for a pen plotter."
)


def validate_square_reference(source: Path) -> tuple[int, int]:
    """Inspect the camera image without rewriting, cropping or padding it."""
    with Image.open(source) as opened:
        width, height = ImageOps.exif_transpose(opened).size
    if width != height:
        raise ValueError(
            f"Input must already be square; received {width}x{height}. "
            "The source file was not modified."
        )
    return width, height


def upload_image(server: str, image_path: Path) -> str:
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with image_path.open("rb") as handle:
        response = requests.post(
            f"{server}/upload/image",
            files={"image": (image_path.name, handle, content_type)},
            data={"type": "input", "overwrite": "true"},
            timeout=120,
        )
    response.raise_for_status()
    result = response.json()
    name = result["name"]
    subfolder = result.get("subfolder") or ""
    return f"{subfolder}/{name}" if subfolder else name


def queue_workflow(server: str, workflow: dict) -> str:
    response = requests.post(
        f"{server}/prompt",
        json={"prompt": workflow, "client_id": str(uuid.uuid4())},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("node_errors"):
        raise RuntimeError(json.dumps(payload["node_errors"], ensure_ascii=False))
    return payload["prompt_id"]


def wait_for_output(server: str, prompt_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(f"{server}/history/{prompt_id}", timeout=30)
        response.raise_for_status()
        record = response.json().get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            for node in record.get("outputs", {}).values():
                images = node.get("images") or []
                if images:
                    return images[0]
        time.sleep(2)
    raise TimeoutError(f"ComfyUI did not finish within {timeout} seconds")


def download_output(server: str, item: dict, destination: Path) -> None:
    query = urlencode(
        {
            "filename": item["filename"],
            "subfolder": item.get("subfolder") or "",
            "type": item.get("type") or "output",
        }
    )
    response = requests.get(f"{server}/view?{query}", timeout=120)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)


def normalize_square_png(source: Path, destination: Path, size: int) -> None:
    """Guarantee a white square raster even if a model/backend changes size."""
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        square = ImageOps.pad(
            image,
            (size, size),
            method=Image.Resampling.LANCZOS,
            color="white",
            centering=(0.5, 0.5),
        )
        square.save(destination, format="PNG")


def zhang_suen_thinning(binary: np.ndarray) -> np.ndarray:
    """Vectorized Zhang-Suen thinning; True pixels become one-pixel paths."""
    image = binary.astype(bool, copy=True)

    def neighbours(value: np.ndarray) -> tuple[np.ndarray, ...]:
        padded = np.pad(value, 1, mode="constant", constant_values=False)
        return (
            padded[:-2, 1:-1],
            padded[:-2, 2:],
            padded[1:-1, 2:],
            padded[2:, 2:],
            padded[2:, 1:-1],
            padded[2:, :-2],
            padded[1:-1, :-2],
            padded[:-2, :-2],
        )

    while True:
        changed = False
        for phase in (0, 1):
            p2, p3, p4, p5, p6, p7, p8, p9 = neighbours(image)
            around = (p2, p3, p4, p5, p6, p7, p8, p9)
            count = sum(item.astype(np.uint8) for item in around)
            transitions = sum(
                ((~around[index]) & around[(index + 1) % 8]).astype(np.uint8)
                for index in range(8)
            )
            if phase == 0:
                triplet_a = p2 & p4 & p6
                triplet_b = p4 & p6 & p8
            else:
                triplet_a = p2 & p4 & p8
                triplet_b = p2 & p6 & p8
            remove = (
                image
                & (count >= 2)
                & (count <= 6)
                & (transitions == 1)
                & ~triplet_a
                & ~triplet_b
            )
            if np.any(remove):
                image[remove] = False
                changed = True
        if not changed:
            return image


def _rdp(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    start = np.asarray(points[0], dtype=float)
    end = np.asarray(points[-1], dtype=float)
    segment = end - start
    length = float(np.linalg.norm(segment))
    middle = np.asarray(points[1:-1], dtype=float)
    if length == 0:
        distances = np.linalg.norm(middle - start, axis=1)
    else:
        relative = middle - start
        distances = np.abs(
            segment[0] * relative[:, 1] - segment[1] * relative[:, 0]
        ) / length
    index = int(np.argmax(distances))
    maximum = float(distances[index])
    if maximum <= epsilon:
        return [points[0], points[-1]]
    split = index + 1
    left = _rdp(points[: split + 1], epsilon)
    right = _rdp(points[split:], epsilon)
    return left[:-1] + right


def trace_skeleton(skeleton: np.ndarray) -> list[list[tuple[float, float]]]:
    pixels = {tuple(item) for item in np.argwhere(skeleton)}
    offsets = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1), (0, 1),
        (1, -1), (1, 0), (1, 1),
    )

    def adjacent(pixel: tuple[int, int]) -> list[tuple[int, int]]:
        row, column = pixel
        return [
            (row + dr, column + dc)
            for dr, dc in offsets
            if (row + dr, column + dc) in pixels
            # A diagonal across an existing orthogonal connection is a
            # shortcut, not a branch. Keeping it creates triangles along
            # normal stair-step curves and fragments them into tiny paths.
            and not (dr and dc and ((row + dr, column) in pixels
                                    or (row, column + dc) in pixels))
        ]

    neighbours = {pixel: adjacent(pixel) for pixel in pixels}
    visited: set[frozenset[tuple[int, int]]] = set()
    paths: list[list[tuple[float, float]]] = []

    def walk(start: tuple[int, int], first: tuple[int, int]) -> list[tuple[float, float]]:
        chain = [start, first]
        visited.add(frozenset((start, first)))
        previous, current = start, first
        while len(neighbours[current]) == 2:
            following = neighbours[current][0]
            if following == previous:
                following = neighbours[current][1]
            edge = frozenset((current, following))
            if edge in visited:
                break
            visited.add(edge)
            chain.append(following)
            previous, current = current, following
        return [(float(column), float(row)) for row, column in chain]

    endpoints = sorted(pixel for pixel in pixels if len(neighbours[pixel]) != 2)
    for start in endpoints:
        for first in neighbours[start]:
            if frozenset((start, first)) not in visited:
                paths.append(walk(start, first))

    for start in sorted(pixels):
        for first in neighbours[start]:
            if frozenset((start, first)) not in visited:
                paths.append(walk(start, first))
    return paths


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(points, points[1:])
    )


def order_paths(paths: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Greedy pen-up optimization; reversing a path is allowed."""
    remaining = paths[:]
    ordered: list[list[tuple[float, float]]] = []
    current = (0.0, 0.0)
    while remaining:
        best_index = 0
        reverse = False
        best_distance = float("inf")
        for index, path in enumerate(remaining):
            start_distance = math.dist(current, path[0])
            end_distance = math.dist(current, path[-1])
            if start_distance < best_distance:
                best_index, reverse, best_distance = index, False, start_distance
            if end_distance < best_distance:
                best_index, reverse, best_distance = index, True, end_distance
        selected = remaining.pop(best_index)
        if reverse:
            selected.reverse()
        ordered.append(selected)
        current = selected[-1]
    return ordered


def raster_to_svg(
    source_png: Path,
    destination_svg: Path,
    preview_png: Path,
    *,
    threshold: int,
    simplify: float,
    minimum_path_length: float,
    paper_mm: float,
    stroke_width: float,
) -> tuple[int, int]:
    with Image.open(source_png) as opened:
        grayscale = np.asarray(opened.convert("L"), dtype=np.uint8)
    binary = grayscale < threshold
    skeleton = zhang_suen_thinning(binary)

    raw_paths = trace_skeleton(skeleton)
    endpoints = Counter(point for path in raw_paths for point in (path[0], path[-1]))
    paths = []
    for path in raw_paths:
        # Keep short connectors between branches: deleting them opens gaps
        # in an otherwise continuous outline. Isolated specks remain filtered.
        bridge = endpoints[path[0]] > 1 and endpoints[path[-1]] > 1
        if path_length(path) < minimum_path_length and not bridge:
            continue
        simplified = _rdp(path, simplify)
        if len(simplified) >= 2:
            paths.append(simplified)
    paths = order_paths(paths)

    height, width = grayscale.shape
    elements = []
    for path in paths:
        commands = [f"M {path[0][0]:.2f} {path[0][1]:.2f}"]
        commands.extend(f"L {x:.2f} {y:.2f}" for x, y in path[1:])
        elements.append(f'    <path d="{" ".join(commands)}" />')
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{paper_mm:g}mm" height="{paper_mm:g}mm" '
        f'viewBox="0 0 {width} {height}">\n'
        f'  <g fill="none" stroke="#000000" stroke-width="{stroke_width:g}" '
        'stroke-linecap="round" stroke-linejoin="round">\n'
        + "\n".join(elements)
        + "\n  </g>\n</svg>\n"
    )
    destination_svg.parent.mkdir(parents=True, exist_ok=True)
    destination_svg.write_text(svg, encoding="utf-8")
    # Preview the paths actually exported, after filtering/simplification.
    preview = Image.new('L', (width, height), 255)
    drawing = ImageDraw.Draw(preview)
    for path in paths:
        drawing.line(path, fill=0, width=max(1, round(stroke_width)))
    preview.save(preview_png)
    return len(paths), int(np.count_nonzero(skeleton))


def main() -> None:
    started = time.monotonic()
    parser = argparse.ArgumentParser(
        description="Generate square Qwen line art plus centerline SVG for a drawing robot."
    )
    parser.add_argument("input", type=Path, help="Photograph containing one person")
    parser.add_argument("output_prefix", type=Path, help="Output path without extension")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seed", type=int, default=6834410345697826643)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--size", type=int, default=1328)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--threshold", type=int, default=210)
    parser.add_argument("--simplify", type=float, default=1.25)
    parser.add_argument("--minimum-path-length", type=float, default=7.0)
    parser.add_argument("--paper-mm", type=float, default=80.0)
    parser.add_argument("--stroke-width", type=float, default=1.25)
    args = parser.parse_args()

    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    validate_square_reference(args.input)
    if args.size < 512 or args.size % 16:
        raise ValueError("--size must be at least 512 and divisible by 16")

    output_png = args.output_prefix.with_suffix(".png")
    raw_output_png = args.output_prefix.with_name(
        args.output_prefix.name + "_ai_raw"
    ).with_suffix(".png")
    output_svg = args.output_prefix.with_suffix(".svg")
    output_png.parent.mkdir(parents=True, exist_ok=True)

    template_path = Path(__file__).with_name("qwen_lineart_workflow_api.json")
    workflow = json.loads(template_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="qwen-lineart-") as temporary:
        temporary_path = Path(temporary)
        raw_result = temporary_path / "raw_result.png"
        workflow["20"]["inputs"]["image"] = upload_image(
            args.server, args.input
        )
        workflow["6"]["inputs"]["prompt"] = args.prompt
        workflow["11"]["inputs"]["seed"] = args.seed
        workflow["11"]["inputs"]["steps"] = args.steps
        workflow["13"]["inputs"]["filename_prefix"] = (
            f"lineart/robot_portrait_{int(time.time())}"
        )

        prompt_id = queue_workflow(args.server, workflow)
        print(f"Queued ComfyUI job: {prompt_id}")
        item = wait_for_output(args.server, prompt_id, args.timeout)
        print(f'AI elapsed: {time.monotonic()-started:.1f} seconds', flush=True)
        download_output(args.server, item, raw_result)
        normalize_square_png(raw_result, raw_output_png, args.size)

    path_count, pixel_count = raster_to_svg(
        raw_output_png,
        output_svg,
        output_png,
        threshold=args.threshold,
        simplify=args.simplify,
        minimum_path_length=args.minimum_path_length,
        paper_mm=args.paper_mm,
        stroke_width=args.stroke_width,
    )
    print(f"Raw AI PNG: {raw_output_png.resolve()}")
    print(f"Final line-only PNG: {output_png.resolve()}")
    print(f"Robot SVG: {output_svg.resolve()}")
    print(f"SVG contains {path_count} unfilled paths from {pixel_count} skeleton pixels")
    print(f'Total elapsed: {time.monotonic()-started:.1f} seconds', flush=True)


if __name__ == "__main__":
    main()
