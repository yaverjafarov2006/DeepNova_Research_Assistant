from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(
    title="Research Assistant API",
    version="1.0.0",
)


# Development üçün frontend-ə icazə verir.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

def clear_cache_files() -> int:
    cache_dir = PROJECT_ROOT / ".cache"

    removed = 0

    if not cache_dir.exists():
        return removed

    for path in cache_dir.rglob("*"):
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    return removed


class AskRequest(BaseModel):
    question: str
    sources: list[str] = [
        "wikipedia",
        "arxiv",
        "web",
    ]
    cache: bool = True
    mode: str = "auto"

def extract_answer(output: str) -> str:
    """
    CLI output-dan yalnız əsas cavabı çıxarır.

    Bunları frontend-ə göndərmir:
    - Sual:
    - İstinadlar:
    - Qeydlər:
    - Vaxtlar:
    """

    lines = output.splitlines()

    answer_lines = []
    started = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("Sual:"):
            started = True
            continue

        if not started:
            continue

        if (
            stripped.startswith("İstinadlar:")
            or stripped.startswith("Qeydlər")
            or stripped.startswith("Vaxtlar:")
        ):
            break

        answer_lines.append(line)

    answer = "\n".join(answer_lines).strip()

    # Format dəyişərsə fallback
    if not answer:
        answer = output.strip()

    return answer


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Research Assistant API is running",
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
    }

@app.post("/api/cache/clear")
async def clear_cache():
    removed = clear_cache_files()

    return {
        "status": "ok",
        "removed": removed,
    }




@app.post("/api/ask")
async def ask(request: AskRequest):

    question = request.question.strip()
    if not request.sources:
        raise HTTPException(
            status_code=400,
            detail="At least one source must be selected.",
        )
    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    env = os.environ.copy()

    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["DENO_SELECTED_SOURCES"] = ",".join(request.sources)
    env["DENO_CACHE_ENABLED"] = str(request.cache).lower()
    env["DENO_MODE"] = request.mode

    if not request.cache:
        clear_cache_files()

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "researcher",
        "ask",
        question,
        cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stdout, stderr = await process.communicate()
    print(stdout.decode("utf-8", errors="replace"))

    if stderr:
        print(stderr.decode("utf-8", errors="replace"))
    
    if not request.cache:
        clear_cache_files()

    output = stdout.decode(
        "utf-8",
        errors="replace",
    )

    error_output = stderr.decode(
        "utf-8",
        errors="replace",
    )

    if process.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                error_output
                or output
                or "Research backend failed."
            ),
        )

    answer = extract_answer(output)

    return {
        "answer": answer,
        "sources": [],
    }