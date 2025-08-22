# Atzmo

Automation experiments for grid-based visual interaction. Currently includes a
prototype script that resizes an image to a square canvas, overlays a 16×16 grid,
and labels each cell with coordinates. The output aims to help a VLM identify UI
locations by referencing grid positions.

## Browser automation container

A Playwright-based container can launch a Chromium browser for scripted mouse,
keyboard, and touch interaction demos.

```sh
docker build -t atzmo-browser browser_container
docker run --rm -it --net=host atzmo-browser
```

## macOS system automation POC

`macos_system_poc.py` showcases OS-level control. It displays prominent
"use at your own risk" warnings and requires the user to type
"I understand the risks" before enabling a button. When activated, it checks for
macOS accessibility permission and instructs on granting or forcing access via
`sudo` commands.

## Setup

Install Pillow:

```sh
python -m pip install -r requirements.txt
```

## Usage

Overlay a grid and coordinate labels onto an image:

```sh
python grid_overlay.py input_image.png output_image.png --size 960 --grid 16
```

The script resizes the source image to fit within the square canvas and writes a
new image with the grid and labels.
