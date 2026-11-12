#!/usr/bin/env python3
"""
duplicate-finder-py — پیدا کردن فایل‌های تکراری (بدون نیاز به pip install)

نمونه استفاده:
    python dupfinder.py ~/Downloads                    # فقط گزارش
    python dupfinder.py ~/Pictures --min-size 100KB    # نادیده گرفتن فایل‌های کوچک
    python dupfinder.py ~/Pictures --move ~/dups       # انتقال تکراری‌ها به یک پوشه
    python dupfinder.py ~/Pictures --delete            # حذف تکراری‌ها (با تأیید)
    python dupfinder.py ~/Pictures --json report.json  # خروجی JSON

روش کار: گروه‌بندی بر اساس اندازه -> هش بخش ابتدایی فایل -> هش کامل SHA-256.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

CHUNK = 1024 * 1024
PARTIAL = 64 * 1024


def parse_size(text: str) -> int:
    text = text.strip().upper().replace(" ", "")
    units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "B": 1}
    for u, mult in units.items():
        if text.endswith(u):
            return int(float(text[: -len(u)]) * mult)
    return int(text)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def hash_file(path: Path, partial: bool = False) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if partial:
            h.update(f.read(PARTIAL))
        else:
            while chunk := f.read(CHUNK):
                h.update(chunk)
    return h.hexdigest()


def scan(root: Path, min_size: int, skip_hidden: bool):
    by_size = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        if skip_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if skip_hidden and name.startswith("."):
                continue
            p = Path(dirpath) / name
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                size = p.stat().st_size
            except OSError:
                continue
            if size >= max(min_size, 1):
                by_size[size].append(p)
    return {s: ps for s, ps in by_size.items() if len(ps) > 1}


def find_duplicates(candidates):
    groups = []
    for size, paths in candidates.items():
        by_partial = defaultdict(list)
        for p in paths:
            try:
                by_partial[hash_file(p, partial=True)].append(p)
            except OSError:
                pass
        for same_partial in by_partial.values():
            if len(same_partial) < 2:
                continue
            by_full = defaultdict(list)
            for p in same_partial:
                try:
                    by_full[hash_file(p)].append(p)
                except OSError:
                    pass
            for digest, same in by_full.items():
                if len(same) > 1:
                    groups.append({"hash": digest, "size": size, "files": sorted(same, key=lambda x: (len(str(x)), str(x)))})
    groups.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    return groups


def main() -> None:
    ap = argparse.ArgumentParser(description="پیدا کردن فایل‌های تکراری")
    ap.add_argument("folder", nargs="?", default=".", help="پوشه برای اسکن (پیش‌فرض: پوشه فعلی)")
    ap.add_argument("--min-size", default="1B", help="حداقل اندازه فایل، مثلا 100KB یا 5MB")
    ap.add_argument("--include-hidden", action="store_true", help="فایل‌ها و پوشه‌های مخفی هم بررسی شوند")
    ap.add_argument("--move", metavar="DIR", help="انتقال نسخه‌های تکراری به این پوشه")
    ap.add_argument("--delete", action="store_true", help="حذف نسخه‌های تکراری (با تأیید)")
    ap.add_argument("--yes", action="store_true", help="بدون پرسیدن تأیید انجام بده")
    ap.add_argument("--json", metavar="FILE", help="ذخیره گزارش در فایل JSON")
    args = ap.parse_args()

    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"پوشه پیدا نشد: {root}")
    if args.move and args.delete:
        sys.exit("--move و --delete را همزمان استفاده نکنید.")

    print(f"در حال اسکن: {root}")
    candidates = scan(root, parse_size(args.min_size), not args.include_hidden)
    groups = find_duplicates(candidates)

    if not groups:
        print("فایل تکراری پیدا نشد. ✨")
        return

    wasted = 0
    for i, g in enumerate(groups, 1):
        extra = g["size"] * (len(g["files"]) - 1)
        wasted += extra
        print(f"\n[{i}] {len(g['files'])} نسخه — هر کدام {human(g['size'])} — هدررفت {human(extra)}")
        for j, f in enumerate(g["files"]):
            print(f"   {'✔ نگه‌داری' if j == 0 else '✗ تکراری '}  {f}")

    total_dups = sum(len(g["files"]) - 1 for g in groups)
    print(f"\nجمع: {len(groups)} گروه، {total_dups} فایل تکراری، قابل آزادسازی: {human(wasted)}")

    if args.json:
        data = [{"hash": g["hash"], "size": g["size"], "files": [str(f) for f in g["files"]]} for g in groups]
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"گزارش JSON ذخیره شد: {args.json}")

    if not (args.move or args.delete):
        print("\nبرای انتقال از --move DIR و برای حذف از --delete استفاده کنید.")
        return

    action = "منتقل" if args.move else "حذف"
    if not args.yes:
        ans = input(f"\n{total_dups} فایل تکراری {action} شوند؟ (اولین نسخه‌ی هر گروه نگه داشته می‌شود) [y/N] ")
        if ans.strip().lower() != "y":
            print("لغو شد.")
            return

    dest = Path(args.move).expanduser().resolve() if args.move else None
    if dest:
        dest.mkdir(parents=True, exist_ok=True)

    done = 0
    for g in groups:
        for f in g["files"][1:]:
            try:
                if dest:
                    target = dest / f.name
                    n = 1
                    while target.exists():
                        target = dest / f"{f.stem} ({n}){f.suffix}"
                        n += 1
                    shutil.move(str(f), str(target))
                else:
                    f.unlink()
                done += 1
            except OSError as e:
                print(f"خطا برای {f}: {e}")
    print(f"{done} فایل {action} شد. {human(wasted)} آزاد شد.")


if __name__ == "__main__":
    main()
