#!/usr/bin/env python3
"""
fix_svg_margins.py — batch-fix "transparent margins" in SVGs

Usage:
  python fix_svg_margins.py INPUT [INPUT ...] [-o OUTDIR] [--method M] [--padding P] [--keep-size]
  python fix_svg_margins.py DIR [-o OUTDIR] [--method M] [--padding P] [--keep-size]

Methods:
  - inkscape      : run Inkscape CLI to crop to drawing (requires Inkscape)  [RECOMMENDED]
  - svgelements   : recompute tight viewBox from actual geometry (pip install svgelements)
  - aspect-slice  : set preserveAspectRatio="xMidYMid slice" (cover), no cropping (may crop *on render*)
  - aspect-none   : set preserveAspectRatio="none" and set width/height to viewBox, no cropping

Examples:
  python fix_svg_margins.py slides/*.svg -o fixed --method inkscape
  python fix_svg_margins.py slides -o fixed --method svgelements --padding 2

Notes:
  • Output files always keep the SAME base name as input and end with .svg in the chosen OUTDIR.
  • Inkscape uses --export-area-drawing to crop to actual content bounds.
"""

import argparse
import sys
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

# ---------- utility ----------

def find_svgs(inputs):
    files = []
    for p in inputs:
        pth = Path(p)
        if pth.is_dir():
            files.extend(sorted(pth.rglob("*.svg")))
            files.extend(sorted(pth.rglob("*.SVG")))
        elif pth.is_file() and pth.suffix.lower() == ".svg":
            files.append(pth)
        else:
            # allow globs passed by shell
            for g in Path().glob(p):
                if g.is_file() and g.suffix.lower() == ".svg":
                    files.append(g)
    # dedupe
    seen = set()
    uniq = []
    for f in files:
        if f not in seen:
            uniq.append(f)
            seen.add(f)
    return uniq

def ensure_outdir(outdir):
    outdir.mkdir(parents=True, exist_ok=True)

def load_xml(path):
    try:
        tree = ET.parse(path)
        return tree
    except ET.ParseError as e:
        print(f"[WARN] Failed to parse {path}: {e}", file=sys.stderr)
        return None

def get_viewbox_dims(svg_root):
    vb = svg_root.attrib.get("viewBox")
    if not vb:
        return None
    parts = vb.strip().split()
    if len(parts) != 4:
        return None
    minx, miny, vbw, vbh = [float(x) for x in parts]
    return minx, miny, vbw, vbh

def write_tree(tree, out_path):
    tree.write(out_path, encoding="utf-8", xml_declaration=True, method="xml")

def out_name_for(src, outdir):
    # Same base name, enforced .svg extension
    return (Path(outdir) / (src.stem + ".svg")).resolve()

# ---------- methods ----------

def method_aspect(tree, mode):
    root = tree.getroot()
    # keep existing viewBox if present; otherwise try to synthesize one from width/height
    vb = get_viewbox_dims(root)
    if not vb:
        width = root.attrib.get("width")
        height = root.attrib.get("height")
        # try to coerce numeric part
        def to_num(x):
            if x is None:
                return None
            try:
                return float("".join(ch for ch in x if (ch.isdigit() or ch in ".-")))
            except Exception:
                return None
        w = to_num(width)
        h = to_num(height)
        if w is not None and h is not None:
            root.set("viewBox", f"0 0 {w} {h}")
            vb = (0.0, 0.0, w, h)
        else:
            # last resort
            root.set("viewBox", "0 0 100 100")
            vb = (0.0, 0.0, 100.0, 100.0)
    root.set("preserveAspectRatio", mode)
    # set explicit width/height to viewBox size (in px) for consistent embedding
    _, _, vbw, vbh = vb
    root.set("width", f"{vbw}px")
    root.set("height", f"{vbh}px")
    return tree

def method_svgelements(path, padding=0.0, keep_size=False):
    try:
        from svgelements import SVG
    except Exception as e:
        print("[ERROR] svgelements is required for --method svgelements. Install with:", file=sys.stderr)
        print("  pip install svgelements", file=sys.stderr)
        raise

    # Parse with svgelements to compute bbox (handles transforms)
    svg = SVG.parse(str(path))
    bbox = None

    def union(bb, other):
        if bb is None:
            return other
        if other is None:
            return bb
        x0 = min(bb.x, other.x)
        y0 = min(bb.y, other.y)
        x1 = max(bb.x + bb.width, other.x + other.width)
        y1 = max(bb.y + bb.height, other.y + other.height)
        class BB:
            pass
        res = BB()
        res.x = x0
        res.y = y0
        res.width = x1 - x0
        res.height = y1 - y0
        return res

    # iterate all elements and union their bboxes
    for e in svg.elements():
        try:
            if getattr(e, "display", None) == "none":
                continue
        except Exception:
            pass
        try:
            bb = e.bbox()
        except Exception:
            bb = None
        if bb is None:
            continue
        bbox = union(bbox, bb)

    if bbox is None:
        raise RuntimeError("Could not compute geometry bbox; is the SVG empty or purely text?")

    # Apply padding
    x = bbox.x - padding
    y = bbox.y - padding
    w = bbox.width + 2 * padding
    h = bbox.height + 2 * padding

    # Load the XML to set viewBox and size
    tree = ET.parse(str(path))
    root = tree.getroot()

    if not keep_size:
        root.set("width", f"{w}px")
        root.set("height", f"{h}px")

    root.set("viewBox", f"{x} {y} {w} {h}")
    return tree

def method_inkscape(in_path, out_path):
    # Inkscape >=1.0 CLI
    cmd = [
        "inkscape",
        "--export-area-drawing",
        "--export-type=svg",
        f"--export-filename={str(out_path)}",
        str(in_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] Inkscape not found in PATH. Install it or use --method svgelements.", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Inkscape failed on {in_path}:\n{e.stderr.decode('utf-8', 'ignore')}", file=sys.stderr)
        return False

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Batch-fix transparent margins in SVG files.")
    ap.add_argument("inputs", nargs="+", help="SVG files, directories, or globs")
    ap.add_argument("-o", "--outdir", default="fixed", help="Output directory (default: fixed)")
    ap.add_argument("--method", choices=["inkscape", "svgelements", "aspect-slice", "aspect-none"],
                    default="inkscape", help="How to fix margins (default: inkscape)")
    ap.add_argument("--padding", type=float, default=0.0, help="Extra padding around tight bbox (svgelements only)")
    ap.add_argument("--keep-size", action="store_true", help="Keep original width/height (svgelements only)")
    args = ap.parse_args()

    svgs = find_svgs(args.inputs)
    if not svgs:
        print("No SVGs found.", file=sys.stderr)
        sys.exit(1)

    outdir = Path(args.outdir)
    ensure_outdir(outdir)

    count_ok = 0
    for src in svgs:
        out_path = out_name_for(src, outdir)  # same base name, forced .svg

        if args.method == "inkscape":
            if method_inkscape(src, out_path):
                count_ok += 1
                print(f"[OK] {src} -> {out_path} (inkscape)")
        elif args.method == "svgelements":
            try:
                tree = method_svgelements(src, padding=args.padding, keep_size=args.keep_size)
                write_tree(tree, out_path)
                count_ok += 1
                print(f"[OK] {src} -> {out_path} (svgelements)")
            except Exception as e:
                print(f"[FAIL] {src}: {e}", file=sys.stderr)
        elif args.method in ("aspect-slice", "aspect-none"):
            tree = load_xml(src)
            if tree is None:
                continue
            mode = "xMidYMid slice" if args.method == "aspect-slice" else "none"
            tree = method_aspect(tree, mode)
            write_tree(tree, out_path)
            count_ok += 1
            print(f"[OK] {src} -> {out_path} ({args.method})")
        else:
            print(f"[ERROR] Unknown method {args.method}", file=sys.stderr)

    print(f"Done. {count_ok}/{len(svgs)} files processed OK. Output in: {outdir.resolve()}")

if __name__ == "__main__":
    main()