"""Render the real page (site/app.js + demo data) to PNG at phone width, without a browser.
Needs: pip install weasyprint pymupdf pillow numpy, and Node. Usage: python3 scripts/preview_site.py [--dark] [--open] [--out DIR]
Limits: WeasyPrint is not a browser. It ignores <details> (folds look open), has no nav icons, and may break text a little
differently, so use it to judge spacing, hierarchy and colour, not pixel positions."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--open", action="store_true", help="expand the first play card")
    ap.add_argument("--out", default="/tmp/preview")
    a = ap.parse_args()
    try:
        import numpy as np
        import pymupdf
        import weasyprint
        from PIL import Image
    except ImportError as exc:
        sys.exit(f"missing {exc.name}: pip install --break-system-packages weasyprint pymupdf pillow numpy")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = "preview" + ("_dark" if a.dark else "") + ("_open" if a.open else "")
    flags = (["dark"] if a.dark else []) + (["open"] if a.open else [])
    subprocess.run(["node", str(ROOT / "scripts" / "preview_dom.js"), str(out / f"{name}.html")] + flags, check=True)
    weasyprint.HTML(str(out / f"{name}.html")).write_pdf(str(out / f"{name}.pdf"))
    pix = pymupdf.open(str(out / f"{name}.pdf"))[0].get_pixmap(dpi=96)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    rows = np.where((np.abs(img.astype(int) - img[2, 2].astype(int)).sum(axis=2) > 12).any(axis=1))[0]
    end = min(pix.height, int(rows.max()) + 24) if len(rows) else pix.height
    Image.fromarray(img[:end]).save(out / f"{name}.png")
    print(out / f"{name}.png", f"{pix.width}x{end}")


if __name__ == "__main__":
    main()
