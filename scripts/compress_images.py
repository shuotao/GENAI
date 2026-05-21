#!/usr/bin/env python3
"""壓縮 + EXIF 自動轉正圖片到目標目錄(不改原檔)。Step 5 出版前用,省 Firebase 流量。

用法: compress_images.py <outdir> <img...> [--maxdim 1600] [--quality 82]
"""
import sys, argparse
from pathlib import Path
from PIL import Image, ImageOps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--maxdim", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=82)
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    tot_in = tot_out = 0
    for f in a.files:
        p = Path(f)
        if not p.exists():
            print(f"  skip(缺檔): {f}"); continue
        im = Image.open(p)
        im = ImageOps.exif_transpose(im)            # 依 EXIF 轉正並烘焙進像素(去掉手機照側轉問題)
        im = im.convert("RGB")
        im.thumbnail((a.maxdim, a.maxdim))           # 等比縮到 maxdim 內
        dst = out / p.name
        im.save(dst, "JPEG", quality=a.quality, optimize=True)
        i, o = p.stat().st_size, dst.stat().st_size
        tot_in += i; tot_out += o
        print(f"  {p.name}: {i//1024}KB → {o//1024}KB")
    if tot_in:
        print(f"  合計: {tot_in//1024//1024}MB → {tot_out//1024//1024}MB  ({tot_out/tot_in:.0%})")


if __name__ == "__main__":
    main()
