"""
Image renderer for DisasterLens scenes.

Produces:
  image_plain.png   — roads, buildings, parks, hazards
  image_labelled.png — same + segment ID labels

Renders at 2× resolution and downsamples for smooth edges.
Hard scenes get Gaussian noise, blur, and JPEG artefacts (seeded).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from dl.generator.models import (
    HazardType,
    Scene,
)

# Colours (R, G, B, A)
COL_ROAD = (180, 180, 180, 255)
COL_ROAD_BORDER = (140, 140, 140, 255)
COL_BUILDING = (200, 180, 160, 255)
COL_BUILDING_BORDER = (120, 100, 80, 255)
COL_PARK = (120, 180, 100, 255)
COL_BACKGROUND = (240, 235, 225, 255)
COL_INTERSECTION = (160, 160, 160, 255)

# Hazard colours
COL_FLOOD = (60, 120, 200, 140)        # translucent blue
COL_DEBRIS = (140, 110, 80, 200)       # brown/grey
COL_FALLEN_TREE = (40, 100, 40, 220)   # dark green
COL_ROAD_DAMAGE = (60, 60, 60, 200)    # dark cracks
COL_DAMAGED_BLDG = (200, 60, 60, 180)  # red-tinted

HAZARD_COLOURS = {
    HazardType.FLOOD: COL_FLOOD,
    HazardType.DEBRIS: COL_DEBRIS,
    HazardType.FALLEN_TREE: COL_FALLEN_TREE,
    HazardType.ROAD_DAMAGE: COL_ROAD_DAMAGE,
    HazardType.DAMAGED_BUILDING: COL_DAMAGED_BLDG,
}

# Label colours
COL_LABEL_BG = (0, 0, 0, 160)
COL_LABEL_TEXT = (255, 255, 255, 255)


def _pts(points: list, scale: float = 1.0) -> list[tuple[float, float]]:
    """Convert list of Point to PIL-compatible coordinate list."""
    return [(p.x * scale, p.y * scale) for p in points]


def _render_base(scene: Scene, scale: float = 2.0) -> Image.Image:
    """Render the base scene at given scale."""
    w = int(scene.image_width * scale)
    h = int(scene.image_height * scale)
    img = Image.new("RGBA", (w, h), COL_BACKGROUND)
    draw = ImageDraw.Draw(img)

    # Parks (draw first, below roads)
    for park in scene.parks:
        coords = _pts(park.polygon, scale)
        if len(coords) >= 3:
            draw.polygon(coords, fill=COL_PARK, outline=(80, 140, 60, 255))

    # Roads
    for seg in scene.road_segments:
        coords = _pts(seg.polygon, scale)
        if len(coords) >= 3:
            draw.polygon(coords, fill=COL_ROAD, outline=COL_ROAD_BORDER)

    # Intersections (small circles)
    r = 6 * scale
    for inter in scene.intersections:
        x, y = inter.x * scale, inter.y * scale
        draw.ellipse([x - r, y - r, x + r, y + r], fill=COL_INTERSECTION)

    # Buildings
    for bldg in scene.buildings:
        coords = _pts(bldg.polygon, scale)
        if len(coords) >= 3:
            draw.polygon(coords, fill=COL_BUILDING, outline=COL_BUILDING_BORDER)

    # Hazards (overlay)
    for hazard in scene.hazards:
        col = HAZARD_COLOURS.get(hazard.type, COL_DEBRIS)
        coords = _pts(hazard.polygon, scale)
        if len(coords) >= 3:
            # Draw on separate layer for alpha blending
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.polygon(coords, fill=col)

            # Add texture for specific hazard types
            if hazard.type == HazardType.FLOOD:
                # Ripple effect: small ellipses
                bbox = hazard.bbox
                for i in range(5):
                    rx = (bbox.x_min + (bbox.x_max - bbox.x_min) * (0.2 + 0.6 * (i / 5))) * scale
                    ry = (bbox.y_min + (bbox.y_max - bbox.y_min) * 0.5) * scale
                    rr = 4 * scale
                    od.ellipse([rx - rr, ry - rr, rx + rr, ry + rr],
                               outline=(80, 140, 220, 100), width=max(1, int(scale)))

            elif hazard.type == HazardType.FALLEN_TREE:
                # Draw trunk line
                bbox = hazard.bbox
                cx = (bbox.x_min + bbox.x_max) / 2 * scale
                cy = (bbox.y_min + bbox.y_max) / 2 * scale
                trunk_len = min(bbox.x_max - bbox.x_min, bbox.y_max - bbox.y_min) * 0.8 * scale
                od.line(
                    [(cx - trunk_len / 2, cy), (cx + trunk_len / 2, cy)],
                    fill=(60, 40, 20, 255), width=max(2, int(3 * scale)),
                )

            elif hazard.type == HazardType.DAMAGED_BUILDING:
                # Red X marking
                bbox = hazard.bbox
                x1, y1 = bbox.x_min * scale, bbox.y_min * scale
                x2, y2 = bbox.x_max * scale, bbox.y_max * scale
                lw = max(2, int(2 * scale))
                od.line([(x1, y1), (x2, y2)], fill=(255, 0, 0, 200), width=lw)
                od.line([(x2, y1), (x1, y2)], fill=(255, 0, 0, 200), width=lw)

            elif hazard.type == HazardType.ROAD_DAMAGE:
                # Crack lines
                bbox = hazard.bbox
                cx = (bbox.x_min + bbox.x_max) / 2 * scale
                cy = (bbox.y_min + bbox.y_max) / 2 * scale
                r2 = min(bbox.x_max - bbox.x_min, bbox.y_max - bbox.y_min) * 0.3 * scale
                od.line([(cx - r2, cy - r2), (cx + r2, cy + r2)],
                        fill=(30, 30, 30, 240), width=max(1, int(2 * scale)))
                od.line([(cx + r2, cy - r2 / 2), (cx - r2 / 2, cy + r2)],
                        fill=(30, 30, 30, 240), width=max(1, int(scale)))

            img = Image.alpha_composite(img, overlay)

    return img


def _add_labels(img: Image.Image, scene: Scene, scale: float = 2.0) -> Image.Image:
    """Add segment ID labels to the image."""
    draw = ImageDraw.Draw(img)
    font_size = max(8, int(9 * scale))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    for seg in scene.road_segments:
        # Label at midpoint of centerline
        if len(seg.centerline) >= 2:
            mx = (seg.centerline[0].x + seg.centerline[1].x) / 2 * scale
            my = (seg.centerline[0].y + seg.centerline[1].y) / 2 * scale
        else:
            continue

        label = seg.id
        bbox = font.getbbox(label)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad = 2 * scale

        # Background rectangle
        draw.rectangle(
            [mx - tw / 2 - pad, my - th / 2 - pad,
             mx + tw / 2 + pad, my + th / 2 + pad],
            fill=COL_LABEL_BG,
        )
        draw.text(
            (mx - tw / 2, my - th / 2),
            label, fill=COL_LABEL_TEXT, font=font,
        )

    return img


def _apply_hard_effects(
    img: Image.Image,
    seed: int,
) -> Image.Image:
    """Apply noise, blur, and JPEG artefacts for hard scenes."""
    rng = np.random.default_rng(seed)

    # Convert to numpy for noise
    arr = np.array(img.convert("RGB")).astype(np.float32)

    # Gaussian noise
    noise = rng.normal(0, 8, arr.shape).astype(np.float32)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")

    # Slight blur
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

    # JPEG compression artefacts
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    buf.seek(0)
    img = Image.open(buf).copy()

    return img.convert("RGBA")


def render_scene(
    scene: Scene,
    output_dir: str,
    apply_hard_effects: bool = False,
) -> tuple[str, str]:
    """Render plain and labelled images for a scene.

    Returns (plain_path, labelled_path).
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    scale = 2.0
    base = _render_base(scene, scale)

    # Downsample
    target = (scene.image_width, scene.image_height)

    # Plain image
    plain = base.copy()
    if apply_hard_effects:
        plain = _apply_hard_effects(plain, scene.seed)
    plain_rgb = plain.convert("RGB").resize(target, Image.LANCZOS)
    plain_path = os.path.join(output_dir, "image_plain.png")
    plain_rgb.save(plain_path, "PNG")

    # Labelled image
    labelled = _add_labels(base.copy(), scene, scale)
    if apply_hard_effects:
        labelled = _apply_hard_effects(labelled, scene.seed + 1000)
    labelled_rgb = labelled.convert("RGB").resize(target, Image.LANCZOS)
    labelled_path = os.path.join(output_dir, "image_labelled.png")
    labelled_rgb.save(labelled_path, "PNG")

    return plain_path, labelled_path
