# DanBooru IMage Utility functions

import cv2
import numpy as np
from PIL import Image


def fill_transparent(image: Image.Image, color='WHITE'):
    image = image.convert('RGBA')
    new_image = Image.new('RGBA', image.size, color)
    new_image.paste(image, mask=image)
    image = new_image.convert('RGB')
    return image


def resize(pic: Image.Image, size: int, keep_ratio=True) -> Image.Image:
    if not keep_ratio:
        target_size = (size, size)
    else:
        min_edge = min(pic.size)
        target_size = (
            int(pic.size[0] / min_edge * size),
            int(pic.size[1] / min_edge * size),
        )

    target_size = (target_size[0] & ~3, target_size[1] & ~3)

    return pic.resize(target_size, resample=Image.Resampling.LANCZOS)


def make_square(img, target_size):
    old_size = img.shape[:2]
    desired_size = max(old_size)
    desired_size = max(desired_size, target_size)

    delta_w = desired_size - old_size[1]
    delta_h = desired_size - old_size[0]
    top, bottom = delta_h // 2, delta_h - (delta_h // 2)
    left, right = delta_w // 2, delta_w - (delta_w // 2)

    color = [255, 255, 255]
    new_im = cv2.copyMakeBorder(
        img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color
    )
    return new_im


def smart_resize(img, size):
    # Assumes the image has already gone through make_square
    if img.shape[0] > size:
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    elif img.shape[0] < size:
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_CUBIC)
    return img
