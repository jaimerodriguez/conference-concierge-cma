"""Render the documentation visuals from their HTML source to PNG.

Each ``*.html`` file in this folder becomes ``docs/images/<name>.png`` at 3600 x 2000 pixels
(a 1800 x 1000 page at 2x). See README.md in this folder for how to run it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

SOURCE = Path(__file__).resolve().parent
IMAGES = SOURCE.parent
WIDTH, HEIGHT, SCALE = 1800, 1000, 2


def render(names: list[str], browser_path: str | None = None) -> list[Path]:
    """Render the named pages (all of them when ``names`` is empty) and return the PNG paths."""
    pages = [SOURCE / f"{name}.html" for name in names] or sorted(SOURCE.glob("*.html"))
    written: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_path)
        for page_file in pages:
            page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=SCALE
            )
            page.goto(page_file.as_uri())
            page.wait_for_load_state("networkidle")
            target = IMAGES / f"{page_file.stem}.png"
            page.screenshot(path=target)
            page.close()
            written.append(target)
        browser.close()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="Page names without .html (default: all).")
    parser.add_argument("--browser", help="Path to a Chromium binary, if not Playwright's own.")
    args = parser.parse_args()
    for path in render(args.names, args.browser):
        print(f"wrote {path.relative_to(IMAGES.parent.parent)}")


if __name__ == "__main__":
    main()
