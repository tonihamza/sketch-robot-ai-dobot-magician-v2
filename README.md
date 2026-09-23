# Sketch Robot with AI and Dobot Magician V2

Generate a square, centerline-only portrait from a webcam photograph with local
Qwen-Image-Edit 2511 and convert it into an 80 × 80 mm SVG for a pen-plotting
workflow such as Dobot Magician V2.

The source photograph is uploaded exactly as provided. It is never cropped,
padded, resized, overwritten, or otherwise modified. The camera is therefore
expected to deliver an already-square image containing one clearly visible
person.

## What the pipeline does

1. Verifies that the source image is square without modifying it.
2. Sends that original image to ComfyUI and Qwen-Image-Edit 2511.
3. Prompts the model for sparse, uniform centerlines and explicitly forbids
   filled areas, shading, gray, color, hatching, background objects and text.
4. Saves the raw AI result separately for inspection.
5. Converts every dark area to a one-pixel centerline skeleton.
6. Traces and simplifies the skeleton into SVG paths.
7. Greedily orders/reverses paths to reduce pen-up travel.
8. Writes an SVG containing only stroked `<path>` elements with `fill="none"`.

The SVG contains no embedded bitmap, background rectangle, mask, filter or
filled shape.

## Required ComfyUI models

- `models/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`
- `models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`
- `models/vae/qwen_image_vae.safetensors`

The workflow also requires the following ComfyUI node types:

- `TextEncodeQwenImageEditPlus`
- `FluxKontextImageScale`
- `FluxKontextMultiReferenceLatentMethod`
- the standard ComfyUI loader, sampler, VAE and image nodes

Model files are not included in this repository and retain their own licenses.

## Install

Use an existing ComfyUI Python environment, or install the small client-side
requirements:

```bash
python -m pip install -r requirements.txt
```

ComfyUI must be running and available at `http://127.0.0.1:8188`.

## Run

```bash
python generate_robot_portrait.py \
  /path/to/square_webcam_photo.jpg \
  /path/to/output/portrait
```

Using a ComfyUI virtual environment directly:

```bash
<COMFYUI_DIR>/.venv/bin/python generate_robot_portrait.py \
  /path/to/square_webcam_photo.jpg \
  /path/to/output/portrait
```

Outputs:

- `portrait_ai_raw.png` — unmodified square AI result, retained for review;
- `portrait.png` — final square, line-only preview matching the vector paths;
- `portrait.svg` — centerline paths for the drawing workflow.

The default physical SVG dimensions are exactly **80 × 80 mm**. They can be
stated explicitly:

```bash
python generate_robot_portrait.py input.jpg portrait --paper-mm 80
```

Useful options:

```text
--seed 6834410345697826643
--steps 40
--threshold 210
--simplify 1.25
--minimum-path-length 7
--stroke-width 1.25
```

The JSON file `qwen_lineart_workflow_api.json` contains the ComfyUI API graph.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Safety

Inspect `portrait.png` and open `portrait.svg` in a vector viewer before sending
it to robot software. For the first physical test, keep the pen above the paper
or use conservative speed and acceleration. This project creates the SVG; it
does not command the robot, bypass safety limits, or perform collision checks.

## License

The code in this repository is available under the MIT License. Qwen,
ComfyUI, model weights, custom nodes, and Dobot software/hardware are separate
projects governed by their respective licenses and terms. This project is not
affiliated with or endorsed by Dobot.
