from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from generate_robot_portrait import raster_to_svg, validate_square_reference, trace_skeleton, DEFAULT_PROMPT
import numpy as np


class VectorizationTests(unittest.TestCase):
    def test_single_person_prompt_and_outline_only_eyebrows(self):
        self.assertIn('portrait of the person in the reference photograph',DEFAULT_PROMPT)
        self.assertIn("Preserve the person's recognizable facial",DEFAULT_PROMPT)
        self.assertIn('Draw only the person: face, hair contours',DEFAULT_PROMPT)
        self.assertNotIn('Subject selection',DEFAULT_PROMPT)
        self.assertNotIn('people',DEFAULT_PROMPT)
        self.assertIn('each eyebrow only as one simple',DEFAULT_PROMPT)
        self.assertIn('completely empty white interior',DEFAULT_PROMPT)
        self.assertIn('No individual eyebrow hairs',DEFAULT_PROMPT)

    def test_short_bridge_between_long_lines_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            image=Image.new('L',(32,32),255);draw=ImageDraw.Draw(image)
            draw.line((8,2,8,29),fill=0);draw.line((11,2,11,29),fill=0)
            draw.line((8,15,11,15),fill=0)
            image.save(root/'source.png')
            raster_to_svg(root/'source.png',root/'out.svg',root/'out.png',threshold=210,simplify=.1,minimum_path_length=7,paper_mm=80,stroke_width=1)
            with Image.open(root/'out.png') as preview:
                self.assertEqual(preview.getpixel((9,15)),0)
                self.assertEqual(preview.getpixel((10,15)),0)

    def test_preview_does_not_show_filtered_specks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);image=Image.new('L',(32,32),255)
            draw=ImageDraw.Draw(image);draw.line((2,5,25,5),fill=0);draw.line((5,20,7,20),fill=0)
            image.save(root/'source.png')
            raster_to_svg(root/'source.png',root/'out.svg',root/'out.png',threshold=210,simplify=.1,minimum_path_length=7,paper_mm=80,stroke_width=1)
            with Image.open(root/'out.png') as preview:self.assertEqual(preview.getpixel((6,20)),255)

    def test_staircase_is_one_continuous_path(self):
        image=np.zeros((30,30),dtype=bool)
        expected=[]
        for i in range(2,20):
            image[i,i]=True;image[i,i+1]=True
            expected.extend([(float(i),float(i)),(float(i+1),float(i))])
        paths=trace_skeleton(image)
        self.assertEqual(len(paths),1)
        self.assertEqual(set(paths[0]),set(expected))

    def test_diagonal_remains_connected(self):
        paths=trace_skeleton(np.eye(20,dtype=bool))
        self.assertEqual(len(paths),1)
        self.assertEqual(len(paths[0]),20)

    def test_true_t_junction_remains_three_branches(self):
        image=np.zeros((20,20),dtype=bool)
        image[5,2:18]=True;image[5:18,10]=True
        paths=trace_skeleton(image)
        self.assertEqual(len(paths),3)
        self.assertTrue(all((10.,5.) in (p[0],p[-1]) for p in paths))

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
