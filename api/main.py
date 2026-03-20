from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

app = FastAPI(
    title="Doctra API",
    description=(
        "Upload a PDF or DOCX document and immediately download a ZIP containing "
        "structured outputs: Markdown, HTML, Excel tables, and extracted images."
    ),
    version="1.0.0",
)

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
WORKER_SCRIPT = Path(__file__).parent / "worker.py"

# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Doctra — Document Parser</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f1f5f9;
      color: #1e293b;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .card {
      background: #ffffff;
      border-radius: 20px;
      box-shadow: 0 4px 32px rgba(0,0,0,.10);
      padding: 52px 44px;
      max-width: 520px;
      width: 100%;
    }
    h1 { font-size: 2.2rem; font-weight: 800; letter-spacing: -.5px; margin-bottom: 6px; }
    .tagline { color: #64748b; font-size: .97rem; margin-bottom: 36px; line-height: 1.5; }
    label { display: block; font-weight: 600; font-size: .88rem; margin-bottom: 10px; letter-spacing: .3px; text-transform: uppercase; color: #475569; }
    .drop {
      width: 100%;
      border: 2.5px dashed #cbd5e1;
      border-radius: 12px;
      padding: 32px 20px;
      text-align: center;
      cursor: pointer;
      transition: border-color .2s, background .2s;
      background: #f8fafc;
      font-size: .9rem;
      color: #64748b;
    }
    .drop:hover { border-color: #6366f1; background: #eef2ff; color: #4f46e5; }
    input[type=file] { display: none; }
    #file-name { margin-top: 10px; font-size: .85rem; color: #475569; min-height: 1.2em; }
    button {
      margin-top: 28px;
      width: 100%;
      padding: 15px;
      background: #6366f1;
      color: #fff;
      border: none;
      border-radius: 10px;
      font-size: 1rem;
      font-weight: 700;
      cursor: pointer;
      transition: background .2s, transform .1s;
      letter-spacing: .2px;
    }
    button:hover:not(:disabled) { background: #4f46e5; transform: translateY(-1px); }
    button:disabled { background: #a5b4fc; cursor: not-allowed; }
    .status { display: none; margin-top: 18px; text-align: center; font-size: .9rem; color: #6366f1; font-weight: 500; }
    .pills { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 28px; }
    .pill { background: #f1f5f9; border-radius: 999px; padding: 6px 14px; font-size: .8rem; color: #475569; font-weight: 500; }
    .footer { margin-top: 28px; font-size: .8rem; color: #94a3b8; text-align: center; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Doctra</h1>
    <p class="tagline">
      Upload a PDF or DOCX document and instantly download a ZIP with
      Markdown, HTML, Excel tables &amp; extracted images.
    </p>

    <form id="form" action="/parse" method="post" enctype="multipart/form-data">
      <label for="file-input">Document</label>
      <div class="drop" id="drop-zone" onclick="document.getElementById('file-input').click()">
        Click to choose a file, or drag &amp; drop here
      </div>
      <input type="file" id="file-input" name="file" accept=".pdf,.docx" required />
      <div id="file-name"></div>
      <button type="submit" id="btn">Parse &amp; Download ZIP</button>
      <div class="status" id="status">Parsing your document — this may take a minute&hellip; &#9203;</div>
    </form>

    <div class="pills">
      <span class="pill">PDF</span>
      <span class="pill">DOCX</span>
      <span class="pill">Markdown output</span>
      <span class="pill">HTML output</span>
      <span class="pill">Excel tables</span>
      <span class="pill">Image extraction</span>
    </div>

    <p class="footer">Powered by Doctra &mdash; open-source document parsing</p>
  </div>

  <script>
    const input = document.getElementById('file-input');
    const nameEl = document.getElementById('file-name');
    const dropZone = document.getElementById('drop-zone');
    const form = document.getElementById('form');
    const btn = document.getElementById('btn');
    const status = document.getElementById('status');

    input.addEventListener('change', () => {
      nameEl.textContent = input.files[0] ? '&#128206; ' + input.files[0].name : '';
    });

    // Drag & drop
    ['dragover', 'dragenter'].forEach(e => {
      dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.style.borderColor = '#6366f1'; });
    });
    ['dragleave', 'drop'].forEach(e => {
      dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.style.borderColor = ''; });
    });
    dropZone.addEventListener('drop', ev => {
      ev.preventDefault();
      if (ev.dataTransfer.files.length) {
        input.files = ev.dataTransfer.files;
        nameEl.textContent = '\uD83D\uDCC4 ' + input.files[0].name;
      }
    });

    form.addEventListener('submit', () => {
      btn.disabled = true;
      btn.textContent = 'Processing\u2026';
      status.style.display = 'block';
    });
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    return _HTML


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}


@app.post("/parse", tags=["parsing"])
async def parse_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF or DOCX document to parse"),
) -> StreamingResponse:
    """
    Upload a document (PDF or DOCX) and receive a ZIP archive containing all
    parsed outputs: Markdown, HTML, Excel tables, and extracted images.

    The download starts automatically when parsing completes.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Accepted: .pdf, .docx",
        )

    # Each request gets its own isolated temp directory so concurrent requests
    # never share the relative `outputs/` path that the parsers write to.
    work_dir = tempfile.mkdtemp(prefix="doctra_")
    # Schedule cleanup after the response is sent
    background_tasks.add_task(shutil.rmtree, work_dir, True)

    try:
        # Save the upload with a stable name so the output directory is predictable
        input_filename = "document" + suffix
        input_path = os.path.join(work_dir, input_filename)
        content = await file.read()
        with open(input_path, "wb") as fh:
            fh.write(content)

        # Run the parser in the isolated working directory
        result = subprocess.run(
            [sys.executable, str(WORKER_SCRIPT), "--file", input_filename, "--type", suffix.lstrip(".")],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=600,  # 10-minute ceiling
        )

        if result.returncode != 0:
            detail = result.stderr[-3000:] if result.stderr else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Parsing failed:\n{detail}")

        outputs_dir = Path(work_dir) / "outputs"
        if not outputs_dir.exists() or not any(outputs_dir.rglob("*")):
            raise HTTPException(status_code=500, detail="Parser produced no output.")

        # Build the ZIP in memory so we can stream it directly
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(outputs_dir.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(outputs_dir))
        zip_buffer.seek(0)

        original_stem = Path(file.filename or "document").stem
        zip_name = f"{original_stem}_parsed.zip"

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Parsing timed out (10 minutes). Try a smaller or simpler document.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
