# ArtModeling website

This is a static, anonymous project website built from nine representative objects. The `site/` directory is the complete publishable bundle; the original capture folders are not needed by the browser.

## Local preview

From the project root, run:

```powershell
python -m http.server 8013 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:8013/` in a browser. A local server is needed for the 3D model viewer to load GLB files.

## Included media

- Nine object cards with start, end, supplemental and masked captures.
- Short RGB and colorized depth interaction excerpts as animated WebP files.
- Lightweight GLB geometry previews exported from the USD models. Their colors approximate the source materials; the previews do not reproduce the full USD physics setup.

The geometry viewer loads the pinned `<model-viewer>` web component from Google's CDN. All object images, animations and geometry are hosted locally in `assets/`.

## Publishing boundary

Publish only the contents of this `site/` directory. The source object folders contain original recordings, USD dependencies and local metadata and must not be copied into a public web root. No author, affiliation, contact or conference information is present in this site.

For the reference-style GitHub Pages URL `https://artmodeling-iclr.github.io/artmodeling-iclr/`, the GitHub account or organization must be named `artmodeling-iclr`, with a public repository named `artmodeling-iclr`. Put the contents of `site/` at that repository's root and enable Pages from the main branch root. The page uses relative asset paths and is ready for this project path. Keep the account profile and commit identity anonymous as well.

To regenerate the curated media from the local source folders, run `python tools\build_site_media.py` and `python tools\export_usd_geometry.py` from the project root.
