from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.database import connect, initialize  # noqa: E402


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:20]}"


def main() -> None:
    library_dir = PROJECT_DIR / "public" / "template-library" / "images"
    manifest_path = library_dir / "manifest.json"
    records = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    categories = list(dict.fromkeys(str(item["category"]) for item in records))
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for item in records:
        key = (str(item["category"]), str(item["templateId"]), str(item["template"]))
        grouped.setdefault(key, []).append(item)

    initialize()
    catalog_templates: list[dict[str, object]] = []
    thumbnail_jobs: list[tuple[Path, Path]] = []
    with connect() as db:
        db.execute("DELETE FROM template_images")
        db.execute("DELETE FROM template_presets")
        db.execute("DELETE FROM template_categories")
        for category_order, category_name in enumerate(categories):
            category_id = stable_id("cat", category_name)
            db.execute(
                "INSERT INTO template_categories(id,name,sort_order) VALUES(?,?,?)",
                (category_id, category_name, category_order),
            )
        category_ids = {
            row["name"]: row["id"]
            for row in db.execute("SELECT id,name FROM template_categories")
        }
        for template_order, ((category, source_id, name), images) in enumerate(grouped.items()):
            template_id = stable_id("tpl", f"{category}:{source_id}")
            db.execute(
                "INSERT INTO template_presets(id,source_id,category_id,name,sort_order,image_count) VALUES(?,?,?,?,?,?)",
                (template_id, source_id, category_ids[category], name, template_order, len(images)),
            )
            catalog_images: list[dict[str, object]] = []
            for image in sorted(images, key=lambda value: int(value["slot"])):
                slot = int(image["slot"])
                suffix = Path(str(image["url"]).split("?", 1)[0]).suffix or ".jpg"
                local_path = library_dir / category / name / f"{slot + 1:02d}{suffix}"
                if not local_path.is_file():
                    raise FileNotFoundError(local_path)
                image_id = stable_id("img", f"{template_id}:{slot}")
                thumb_path = PROJECT_DIR / "public" / "template-library" / "thumbs" / f"{image_id}.jpg"
                web_image = f"/template-library/images/{quote(category)}/{quote(name)}/{quote(local_path.name)}"
                web_thumb = f"/template-library/thumbs/{image_id}.jpg"
                db.execute(
                    "INSERT INTO template_images(id,template_id,slot_index,original_url,local_path) VALUES(?,?,?,?,?)",
                    (image_id, template_id, slot, str(image["url"]), str(local_path)),
                )
                thumbnail_jobs.append((local_path, thumb_path))
                catalog_images.append({"id": image_id, "slot": slot, "thumbnail_url": web_thumb, "image_url": web_image})
            catalog_templates.append(
                {
                    "id": template_id,
                    "name": name,
                    "image_count": len(catalog_images),
                    "category_id": category_ids[category],
                    "category_name": category,
                    "previews": [{"id": item["id"], "url": item["thumbnail_url"]} for item in catalog_images[:4]],
                    "images": catalog_images,
                }
            )
        db.execute("PRAGMA optimize")

    def make_thumbnail(job: tuple[Path, Path]) -> None:
        source, target = job
        if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((420, 420), Image.Resampling.LANCZOS)
            image.save(target, "JPEG", quality=82, optimize=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(make_thumbnail, thumbnail_jobs))

    category_counts = {category: 0 for category in categories}
    for item in catalog_templates:
        category_counts[str(item["category_name"])] += 1
    catalog = {
        "categories": [
            {"id": stable_id("cat", name), "name": name, "template_count": category_counts[name]}
            for name in categories
        ],
        "templates": catalog_templates,
    }
    catalog_path = PROJECT_DIR / "public" / "template-library" / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(json.dumps({"categories": len(categories), "templates": len(grouped), "images": len(records), "catalog": str(catalog_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
