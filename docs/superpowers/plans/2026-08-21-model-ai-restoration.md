# Existing Model Preset AI Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faithfully AI-restore the 20 currently enabled model preset images to at least 1000 px on the short edge, preserve each image's existing small upper-left purple marker, and switch the local website database to the approved restored files without changing the unused model library.

**Architecture:** Treat the SQLite database as the source of truth for the exact 20 enabled inputs. Generate non-destructive AI-edited PNGs into a separate directory, validate them with a test-driven Python verifier plus visual review, then perform one transactional database activation after creating a recoverable backup. The existing FastAPI `quality=thumb` and `quality=hd` paths remain unchanged: the grid receives cached 256 px thumbnails and the confirmation dialog receives the restored high-resolution source/cached HD preview.

**Tech Stack:** Python 3.12, Pillow, SQLite, FastAPI, React 19/Vinext, Node.js test runner, built-in ImageGen editing, PowerShell.

---

## File map

- Create: `backend/tests/test_verify_ai_models.py`
- Create: `backend/scripts/verify_ai_models.py`
- Create: `backend/tests/test_activate_ai_models.py`
- Create: `backend/scripts/activate_ai_models.py`
- Create/generated: `backend/data/model-ai-restored/approved_model_01-ai-hd.png` through `approved_model_20-ai-hd.png`
- Create automatically: `backend/data/studio.before-model-ai-restoration.sqlite3`
- Modify automatically after approval: `backend/data/studio.sqlite3` (`model_presets.avatar_path` only)
- Verify without modification: `backend/app/main.py`, `app/ui/CyberStudio.tsx`, `tests/rendered-html.test.mjs`

### Task 1: Lock the input set and write the failing restoration verifier tests

- [ ] Query the database for the exact enabled inputs and confirm there are 20 unique rows whose current files exist:

  ```powershell
  python -c "import sqlite3, pathlib; db=sqlite3.connect(r'backend/data/studio.sqlite3'); rows=db.execute('SELECT id, avatar_path FROM model_presets WHERE enabled=1 ORDER BY sort_order, created_at DESC').fetchall(); print('enabled=', len(rows)); [print(i, pathlib.Path(p).name, pathlib.Path(p).is_file()) for i,p in rows]"
  ```

  Expected: `enabled= 20`, followed by 20 `True` lines for `approved_model_01` through `approved_model_20`. Do not include `pajama-model-*` files.

- [ ] Create `backend/tests/test_verify_ai_models.py` using temporary images. Cover these exact behaviors:

  ```python
  from pathlib import Path
  from tempfile import TemporaryDirectory
  import unittest

  from PIL import Image, ImageDraw

  from backend.scripts.verify_ai_models import inspect_restored_models, purple_marker_ratio


  class VerifyAiModelsTest(unittest.TestCase):
      def make_image(self, path: Path, size: int, marker_diameter: int) -> None:
          image = Image.new("RGB", (size, size), "#e8e9ed")
          draw = ImageDraw.Draw(image)
          draw.ellipse((24, 24, 24 + marker_diameter, 24 + marker_diameter), fill="#8457ff")
          image.save(path)

      def test_accepts_twenty_large_images_with_small_markers(self) -> None:
          with TemporaryDirectory() as folder:
              root = Path(folder)
              for number in range(1, 21):
                  self.make_image(root / f"approved_model_{number:02d}-ai-hd.png", 1200, 36)
              failures, ratios = inspect_restored_models(root)
              self.assertEqual(failures, [])
              self.assertEqual(len(ratios), 20)

      def test_rejects_missing_images_low_resolution_and_large_marker(self) -> None:
          with TemporaryDirectory() as folder:
              root = Path(folder)
              self.make_image(root / "approved_model_01-ai-hd.png", 800, 160)
              failures, _ = inspect_restored_models(root)
              self.assertTrue(any("expected 20" in failure for failure in failures))
              self.assertTrue(any("only 800x800" in failure for failure in failures))
              self.assertTrue(any("purple marker ratio" in failure for failure in failures))

      def test_marker_ratio_ignores_non_purple_content(self) -> None:
          with TemporaryDirectory() as folder:
              path = Path(folder) / "plain.png"
              Image.new("RGB", (1200, 1200), "white").save(path)
              self.assertEqual(purple_marker_ratio(path), 0)


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] Run the test before creating the implementation:

  ```powershell
  python -m unittest backend.tests.test_verify_ai_models -v
  ```

  Expected: FAIL with `ModuleNotFoundError: No module named 'backend.scripts.verify_ai_models'`.

- [ ] Commit only the new failing test:

  ```powershell
  git add backend/tests/test_verify_ai_models.py
  git commit -m "test: define model restoration validation"
  ```

### Task 2: Implement the restoration verifier

- [ ] Create `backend/scripts/verify_ai_models.py` with reusable `purple_marker_ratio(path)` and `inspect_restored_models(root)` functions. The implementation must:

  - Match only `approved_model_??-ai-hd.png`.
  - Require exactly 20 files.
  - Require each image's short edge to be at least 1000 px.
  - Search only the upper-left 18% × 18% for saturated purple pixels.
  - Measure the enabled source portraits first (observed `0.098..0.102`) and accept a preserved marker ratio from `0.075` through `0.125`; reject the composition library's large-dot scale.
  - Return `(failures, ratios)` for unit testing and print a concise summary from `main()`.

- [ ] Run the focused tests:

  ```powershell
  python -m unittest backend.tests.test_verify_ai_models -v
  ```

  Expected: 3 tests pass.

- [ ] Run the verifier against the not-yet-generated destination:

  ```powershell
  python backend/scripts/verify_ai_models.py
  ```

  Expected: FAIL with `expected 20 restored images` until generation is complete.

- [ ] Commit verifier and passing tests:

  ```powershell
  git add backend/scripts/verify_ai_models.py backend/tests/test_verify_ai_models.py
  git commit -m "feat: validate restored model presets"
  ```

### Task 3: AI-restore the 20 enabled model presets non-destructively

- [ ] Create `backend/data/model-ai-restored/` and process the database rows in sort order. Before each edit, inspect the source with the local image viewer. Use the built-in image editing model once per source image and save the returned bitmap as the corresponding stable PNG filename.

- [ ] Use this exact editing brief for every source image:

  ```text
  Use case: identity-preserve.
  Asset type: high-resolution model preset for a local furniture-image studio.
  Faithfully AI-restore and upscale this exact input image. Preserve the same person's identity, facial features, expression, hairstyle, body proportions, pose, hand placement, framing, crop, camera angle, clothing design, clothing color, fabric relationship, and background. Improve only real image clarity: facial and hair definition, fabric texture, clean edges, anti-aliasing, and natural high-resolution detail. CRITICAL UI MARKER: preserve the existing small purple circular marker in the upper-left at the same relative position and small relative diameter; keep it a small purple dot and do not enlarge it into the composition-library large-dot style. Do not add or remove people, text, logos, watermarks, accessories, furniture, props, or background objects. Do not beautify, restyle, recolor, change wardrobe, change pose, or change composition. Output one square high-resolution PNG with a short edge of at least 1000 pixels.
  ```

- [ ] Generate in four resumable batches and skip any already approved destination file:

  - Batch A: `approved_model_01`–`approved_model_05`
  - Batch B: `approved_model_06`–`approved_model_10`
  - Batch C: `approved_model_11`–`approved_model_15`
  - Batch D: `approved_model_16`–`approved_model_20`

- [ ] After each batch, run:

  ```powershell
  Get-ChildItem -LiteralPath 'backend/data/model-ai-restored' -Filter 'approved_model_??-ai-hd.png' | Sort-Object Name | Select-Object Name,Length
  ```

  Expected after Batch D: exactly 20 non-empty PNG files. Never overwrite files in `backend/data/preset-models/`.

### Task 4: Validate and visually review every restored model image

- [ ] Run automated validation:

  ```powershell
  python backend/scripts/verify_ai_models.py
  ```

  Expected: `images=20`, minimum dimensions at least 1000 px, and every source-sized marker ratio within `0.075..0.125`.

- [ ] Build a contact sheet for review using Pillow as a read-only formatting step, then inspect it with the local image viewer. Check all 20 pairs for identity, face, hair, pose, crop, clothing style/color/material, background, and small-dot consistency. Do not accept a result merely because its dimensions pass.

- [ ] For each rejected image, delete only that generated destination, re-edit its original with a problem-specific sentence appended to the fixed brief, and rerun the verifier. Typical correction sentences are:

  ```text
  Previous result changed the face; reproduce the input face and expression exactly.
  Previous result changed the clothing; reproduce the input garment design and color exactly.
  Previous result enlarged the UI marker; keep the upper-left purple dot at the original small diameter.
  ```

- [ ] Do not proceed until all 20 automated checks pass and the contact-sheet comparison passes visually.

### Task 5: Write and test the transactional database activation

- [ ] Create `backend/tests/test_activate_ai_models.py`. Use a temporary SQLite database containing 20 enabled rows plus one disabled row. Assert that `activate(db_path, restored_dir, backup_path)`:

  - Creates the backup once.
  - Updates exactly the 20 enabled `approved_model_01`–`approved_model_20` rows.
  - Leaves the disabled row unchanged.
  - Rejects a missing restored file before any row changes.
  - Finishes with `PRAGMA integrity_check = ok`.

- [ ] Run the test before implementation:

  ```powershell
  python -m unittest backend.tests.test_activate_ai_models -v
  ```

  Expected: FAIL because `backend.scripts.activate_ai_models` does not exist.

- [ ] Create `backend/scripts/activate_ai_models.py` with constants:

  ```python
  ROOT = Path(__file__).resolve().parents[1]
  DB_PATH = ROOT / "data" / "studio.sqlite3"
  BACKUP_PATH = ROOT / "data" / "studio.before-model-ai-restoration.sqlite3"
  RESTORED_DIR = ROOT / "data" / "model-ai-restored"
  ```

  Implement `activate(db_path, restored_dir, backup_path)` so it validates all files before mutation, copies the database only when the backup does not already exist, opens `BEGIN IMMEDIATE`, maps each filename stem `approved_model_XX-ai-hd.png` to preset ID `approved_model_XX`, updates only `WHERE id=? AND enabled=1`, requires `rowcount == 1`, checks database integrity, and rolls back automatically on failure.

- [ ] Run the activation tests:

  ```powershell
  python -m unittest backend.tests.test_activate_ai_models -v
  ```

  Expected: all tests pass.

- [ ] Run the production activation once:

  ```powershell
  python backend/scripts/activate_ai_models.py
  ```

  Expected: `activated=20 integrity=ok` and backup path `backend/data/studio.before-model-ai-restoration.sqlite3`.

- [ ] Commit the activation script and its tests, but do not commit generated images or SQLite databases unless they are already intentionally tracked by the project:

  ```powershell
  git add backend/scripts/activate_ai_models.py backend/tests/test_activate_ai_models.py
  git commit -m "feat: activate restored model presets safely"
  ```

### Task 6: Verify database, API qualities, frontend confirmation flow, and local site

- [ ] Verify the database points to all 20 existing restored files and remains healthy:

  ```powershell
  python -c "import sqlite3, pathlib; db=sqlite3.connect(r'backend/data/studio.sqlite3'); rows=db.execute('SELECT id,avatar_path FROM model_presets WHERE enabled=1 ORDER BY sort_order,created_at DESC').fetchall(); print('enabled=',len(rows),'restored=',sum('model-ai-restored' in p and pathlib.Path(p).is_file() for _,p in rows),'integrity=',db.execute('PRAGMA integrity_check').fetchone()[0])"
  ```

  Expected: `enabled= 20 restored= 20 integrity= ok`.

- [ ] Run all Python restoration tests and syntax compilation:

  ```powershell
  python -m unittest discover -s backend/tests -v
  python -m compileall backend/app backend/scripts
  ```

  Expected: all tests pass; compilation exits 0.

- [ ] Run frontend build and rendered-page tests:

  ```powershell
  npm run build
  node --test tests/rendered-html.test.mjs
  ```

  Expected: build succeeds and all three Node tests pass.

- [ ] Ensure the local FastAPI service and local Vinext frontend are running. If either must be started, use hidden background windows. Then verify:

  ```powershell
  Invoke-RestMethod 'http://localhost:8000/api/presets/models' | ConvertTo-Json -Depth 5
  Invoke-WebRequest 'http://localhost:8000/api/preset-files/models/approved_model_01?quality=thumb' -OutFile "$env:TEMP\approved-model-thumb.png"
  Invoke-WebRequest 'http://localhost:8000/api/preset-files/models/approved_model_01?quality=hd' -OutFile "$env:TEMP\approved-model-hd.png"
  python -c "from PIL import Image; import os; a=Image.open(os.path.join(os.environ['TEMP'],'approved-model-thumb.png')); b=Image.open(os.path.join(os.environ['TEMP'],'approved-model-hd.png')); print('thumb=',a.size,'hd=',b.size)"
  (Invoke-WebRequest 'http://localhost:3000/studio').StatusCode
  ```

  Expected: API returns 20 model presets; thumbnail max edge is at most 256 px; HD short edge is at least 1000 px; `/studio` returns `200`.

- [ ] In the browser, open the model library, click at least the first, middle, and last restored model, and verify each opens the existing enlarged confirmation dialog with `返回重选` and `确认选择`. Confirm grid cards still show a small purple dot and no large composition-style marker.

- [ ] Leave the local services running and report the local URL `http://localhost:3000/studio`. Do not publish or modify hosting configuration.

## Rollback

If activation or page validation fails, stop the backend, verify both database paths resolve under `backend/data/`, then copy `backend/data/studio.before-model-ai-restoration.sqlite3` over `backend/data/studio.sqlite3` with `Copy-Item -LiteralPath ... -Destination ... -Force`, restart the backend, and rerun the database/API checks. The original preset images remain untouched throughout.
