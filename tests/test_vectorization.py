from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from generate_robot_portrait import raster_to_svg, validate_square_reference


class VectorizationTests(unittest.TestCase):
    def test_square_source_is_not_modified_and_svg_has_only_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            image = Image.new("RGB", (128, 128), "white")
            drawing = ImageDraw.Draw(image)
            drawing.ellipse((25, 15, 103, 108), outline="black", width=5)
            drawing.rectangle((50, 45, 78, 60), fill="black")
            image.save(source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()

            self.assertEqual(validate_square_reference(source), (128, 128))
            paths, _ = raster_to_svg(
                source,
                root / "portrait.svg",
                root / "portrait.png",
                threshold=210,
                simplify=1.25,
                minimum_path_length=7,
                paper_mm=80,
                stroke_width=1.25,
            )

            after = hashlib.sha256(source.read_bytes()).hexdigest()
            svg = (root / "portrait.svg").read_text(encoding="utf-8")
            self.assertEqual(before, after)
            self.assertGreater(paths, 0)
            self.assertIn('width="80mm" height="80mm"', svg)
            self.assertIn('fill="none"', svg)
            self.assertNotIn("<image", svg)
            self.assertNotIn("<rect", svg)

    def test_non_square_source_is_rejected_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.png"
            Image.new("RGB", (128, 96), "white").save(source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "already be square"):
                validate_square_reference(source)
            after = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
