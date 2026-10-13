"""CLIP image features, cleaned up from the exploration notebook.

What changed vs the notebook, and why:
  * models load ONCE per process (the notebook reloaded ViT-large for every image)
  * the image is encoded ONCE (the notebook re-encoded it for colour, size, shape, category)
  * ViT-large dropped: CLIP alone gives the embedding we match on
  * size/shape/colour labels dropped: no scale reference in a photo, and colour is already in the embedding
  * OCR dropped: it reads names and ID numbers off cards, which we should not store, and EasyOCR is >1 GB
  * EXIF is stripped (we only keep pixels) and image size is capped
"""
import io
import os
from functools import lru_cache

import torch
from PIL import Image, ImageOps
from transformers import CLIPModel, CLIPProcessor

MODEL_NAME = os.environ.get("CLIP_MODEL", "openai/clip-vit-base-patch32")
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow raises DecompressionBombError above 2x this


class UnreadableImage(Exception):
    """The upload is not a usable image. Retrying will not help."""


@lru_cache(maxsize=1)
def _load():
    model = CLIPModel.from_pretrained(MODEL_NAME).eval()
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    return model, processor


def _as_tensor(output):
    # transformers returns a tensor in 4.x; be tolerant of wrapper objects
    return output if torch.is_tensor(output) else output.pooler_output


def open_image(data):
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # honour rotation, then drop all metadata by not saving it
        return img.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise UnreadableImage(str(e)) from e


def embed(data):
    """Return an L2-normalised 512-d CLIP image embedding as a list of floats."""
    model, processor = _load()
    image = open_image(data)
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        vec = _as_tensor(model.get_image_features(**inputs))[0]
        vec = vec / vec.norm()
    return vec.tolist()
