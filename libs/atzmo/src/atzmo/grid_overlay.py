import argparse
from PIL import Image, ImageDraw, ImageFont, ImageChops


def overlay_grid(input_path: str, output_path: str, size: int = 960, grid: int = 16) -> None:
    """Resize image to a square canvas, overlay a labeled grid, and save it.

    The image is scaled to fit within a size x size square while preserving aspect
    ratio. Empty space is padded with black. A grid is drawn using a difference
    filter so lines remain visible regardless of background. Each cell is labeled
    with its (x, y) coordinate.

    Args:
        input_path: Path to the source image.
        output_path: Where to write the processed image.
        size: Size of the output square image in pixels.
        grid: Number of grid cells per side.
    """

    img = Image.open(input_path)
    ratio = min(size / img.width, size / img.height)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    resized = img.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    paste_pos = ((size - new_size[0]) // 2, (size - new_size[1]) // 2)
    canvas.paste(resized, paste_pos)

    overlay = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cell = size // grid

    for i in range(grid + 1):
        draw.line((i * cell, 0, i * cell, size), fill="white")
        draw.line((0, i * cell, size, i * cell), fill="white")

    font = ImageFont.load_default()
    for y in range(grid):
        for x in range(grid):
            label = f"{x},{y}"
            text_pos = (x * cell + 2, y * cell + 2)
            draw.text(text_pos, label, fill="white", font=font)

    result = ImageChops.difference(canvas, overlay)
    result.save(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Overlay a grid and coordinate labels on an image.")
    parser.add_argument("input", help="Path to input image")
    parser.add_argument("output", help="Path to output image")
    parser.add_argument("--size", type=int, default=960, help="Output image size (square)")
    parser.add_argument("--grid", type=int, default=16, help="Number of grid cells per side")
    args = parser.parse_args()
    overlay_grid(args.input, args.output, size=args.size, grid=args.grid)
