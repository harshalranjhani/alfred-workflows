#!/usr/bin/env python3
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
archive = dist / "PR Review.alfredworkflow"

with ZipFile(archive, "w", ZIP_DEFLATED) as package:
    for name in ("info.plist", "icon.png", "Review.alfredui/ui.json",
                 "Review.alfredui/review.py", "Review.alfredui/review.md",
                 "Review.alfredui/rereview.md"):
        package.write(root / "workflow" / name, name)

print(archive)
