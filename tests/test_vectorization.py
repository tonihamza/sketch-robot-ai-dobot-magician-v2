from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from generate_robot_portrait import raster_to_svg, validate_square_reference, trace_skeleton, DEFAULT_PROMPT, extract_solid_details
import numpy as np


class VectorizationTests(unittest.TestCase):
    def test_workflow_uses_same_photo_fidelity_prompt_as_cli(self):
        workflow=json.loads((Path(__file__).resolve().parents[1]/'qwen_lineart_workflow_api.json').read_text())
        self.assertEqual(workflow['6']['inputs']['prompt'],DEFAULT_PROMPT)
        self.assertIn('closed lips must stay touching',DEFAULT_PROMPT)
        self.assertIn('original eye shapes and pupil positions',DEFAULT_PROMPT)
        self.assertNotIn('Create a centered',DEFAULT_PROMPT)

    def test_filled_pupils_become_closed_outlines_instead_of_disappearing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);im=Image.new('L',(512,512),255);draw=ImageDraw.Draw(im)
            draw.ellipse((120,200,130,210),fill=0)
            draw.ellipse((370,200,380,210),fill=0)
            draw.point((30,30),fill=0);im.save(root/'source.png')
            remaining,details=extract_solid_details(np.asarray(im)<210,80)
            self.assertEqual(len(details),2)
            self.assertTrue(all(p[0]==p[-1] and len(p)>=4 for p in details))
            self.assertEqual(int(remaining.sum()),1)  # speck is not promoted to a pupil
            count,_=raster_to_svg(root/'source.png',root/'out.svg',root/'out.png',threshold=210,simplify=1.25,minimum_path_length=7,paper_mm=80,stroke_width=1)
            self.assertEqual(count,2)
            self.assertIn('fill="none"',(root/'out.svg').read_text())
            with Image.open(root/'out.png') as preview:
                self.assertEqual(preview.getpixel((125,205)),255)  # outline, not fill
                self.assertLess(preview.getpixel((125,200)),128)
                self.assertEqual(preview.getpixel((30,30)),255)

    def test_rings_long_strokes_and_large_fills_are_not_replaced(self):
        im=Image.new('L',(512,512),255);draw=ImageDraw.Draw(im)
        draw.ellipse((20,20,31,31),outline=0,width=3)
        draw.rectangle((80,80,180,100),fill=0)
        draw.line((40,150,80,150),fill=0,width=3)
        original=np.asarray(im)<210
        remaining,details=extract_solid_details(original,80)
        self.assertEqual(details,[]);np.testing.assert_array_equal(remaining,original)

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
            self.assertIn('Q ', svg)
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
