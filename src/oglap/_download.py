"""
Async S3 download with streaming progress, slow-network detection,
and local file caching to ``oglap-data/{version}/``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from ._constants import (
    OGLAP_DATA_DIR_DEFAULT,
    OGLAP_REMOTE_FILES,
    OGLAP_S3_BASE,
    SLOW_BPS,
    SLOW_WINDOW_MS,
)


async def fetch_with_progress(
    url: str,
    *,
    on_chunk: Callable[..., None] | None = None,
    timeout_ms: int = 120_000,
) -> str:
    """Download *url* with streaming progress and slow-network detection.

    Returns the response body as a string.
    """
    timeout = httpx.Timeout(timeout_ms / 1000, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise RuntimeError(
                    f"HTTP {response.status_code}"
                    + (f" {response.reason_phrase}" if response.reason_phrase else "")
                )

            total = int(response.headers.get("content-length", "0"))
            chunks: list[bytes] = []
            loaded = 0
            win_start = time.monotonic()
            win_bytes = 0

            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                loaded += len(chunk)
                win_bytes += len(chunk)

                now = time.monotonic()
                elapsed_ms = (now - win_start) * 1000
                slow = False
                if elapsed_ms >= SLOW_WINDOW_MS:
                    speed_bps = (win_bytes / elapsed_ms) * 1000
                    slow = speed_bps < SLOW_BPS
                    win_start = now
                    win_bytes = 0

                if on_chunk:
                    pct = round((loaded / total) * 1000) / 10 if total else 0
                    on_chunk(loaded=loaded, total=total, percent=pct, slow=slow)

    return b"".join(chunks).decode("utf-8")


async def init_oglap_download(opts: dict[str, Any]) -> dict[str, Any]:
    """Download mode: fetch files from S3, cache locally, return loaded data.

    Returns ``{profile, localities, data, checks, version_dir}``.
    """
    version = opts.get("version") or "latest"
    base_url = opts.get("base_url") or OGLAP_S3_BASE
    data_dir = opts.get("data_dir") or OGLAP_DATA_DIR_DEFAULT
    force_download = bool(opts.get("force_download"))
    on_progress: Callable[..., None] = opts.get("on_progress") or (lambda **kw: None)
    v_url = f"{base_url}/{version}"
    checks: list[dict[str, str]] = []
    loaded: dict[str, Any] = {}

    # ── Resolve & create local data directory ──
    version_dir = Path(data_dir).resolve() / version
    try:
        version_dir.mkdir(parents=True, exist_ok=True)
        checks.append({"id": "storage.dir", "status": "pass", "message": f"Data directory ready: {version_dir}"})
    except OSError as e:
        checks.append({"id": "storage.dir", "status": "fail", "message": f"Cannot create data directory: {e}"})
        return {
            "profile": None,
            "localities": None,
            "data": None,
            "checks": checks,
            "version_dir": str(version_dir),
            "error": checks[-1]["message"],
        }

    # ── Helper: get a file (from cache or download + save) ──
    async def get_file(file_spec: dict[str, Any], step: int, total_steps: int) -> Any:
        file_path = version_dir / file_spec["name"]

        # Try local cache first (unless forced)
        if not force_download and file_path.exists():
            on_progress(
                file=file_spec["name"], label=file_spec["label"],
                step=step, totalSteps=total_steps,
                status="cached", loaded=0, total=0, percent=100,
            )
            try:
                text = file_path.read_text(encoding="utf-8")
                parsed = json.loads(text)
                checks.append({
                    "id": f"local.{file_spec['key']}",
                    "status": "pass",
                    "message": f"{file_spec['label']}: loaded from local cache.",
                })
                return parsed
            except (json.JSONDecodeError, OSError) as e:
                checks.append({
                    "id": f"local.{file_spec['key']}",
                    "status": "warn",
                    "message": f"Local {file_spec['label']} is invalid ({e}), re-downloading.",
                })

        # Download from S3
        slow_notified = False

        def handle_chunk(*, loaded: int, total: int, percent: float, slow: bool) -> None:
            nonlocal slow_notified
            if slow and not slow_notified:
                slow_notified = True
                on_progress(
                    file=file_spec["name"], label=file_spec["label"],
                    step=step, totalSteps=total_steps,
                    status="slow", loaded=loaded, total=total, percent=percent,
                )
            on_progress(
                file=file_spec["name"], label=file_spec["label"],
                step=step, totalSteps=total_steps,
                status="downloading", loaded=loaded, total=total, percent=percent,
            )

        on_progress(
            file=file_spec["name"], label=file_spec["label"],
            step=step, totalSteps=total_steps,
            status="downloading", loaded=0, total=0, percent=0,
        )

        text = await fetch_with_progress(
            f"{v_url}/{file_spec['name']}",
            on_chunk=handle_chunk,
            timeout_ms=file_spec.get("timeout_ms", 120_000),
        )

        # Parse JSON
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {file_spec['name']}: {e}") from e

        # Save to local cache
        try:
            file_path.write_text(text, encoding="utf-8")
            checks.append({
                "id": f"save.{file_spec['key']}",
                "status": "pass",
                "message": f"{file_spec['label']}: downloaded and saved to {file_path}",
            })
        except OSError as e:
            checks.append({
                "id": f"save.{file_spec['key']}",
                "status": "warn",
                "message": f"{file_spec['label']}: downloaded but failed to save locally ({e}).",
            })

        on_progress(
            file=file_spec["name"], label=file_spec["label"],
            step=step, totalSteps=total_steps,
            status="done", loaded=0, total=0, percent=100,
        )
        return parsed

    # ── Helper: report failure ──
    def file_fail(file_spec: dict[str, Any], step: int, err: Exception) -> dict[str, Any]:
        on_progress(
            file=file_spec["name"], label=file_spec["label"],
            step=step, totalSteps=3,
            status="error", loaded=0, total=0, percent=0, error=str(err),
        )
        checks.append({
            "id": f"fetch.{file_spec['key']}",
            "status": "fail",
            "message": f"Failed to get {file_spec['label']}: {err}",
        })
        return {
            "profile": None, "localities": None, "data": None,
            "checks": checks,
            "version_dir": str(version_dir),
            "error": checks[-1]["message"],
        }

    # Step 1/3: Country profile
    try:
        loaded["profile"] = await get_file(OGLAP_REMOTE_FILES[0], 1, 3)
    except Exception as err:
        return file_fail(OGLAP_REMOTE_FILES[0], 1, err)

    # Step 2/3: Localities naming
    try:
        loaded["localities"] = await get_file(OGLAP_REMOTE_FILES[1], 2, 3)
    except Exception as err:
        return file_fail(OGLAP_REMOTE_FILES[1], 2, err)

    # Step 3/3: Places database (large)
    try:
        loaded["data"] = await get_file(OGLAP_REMOTE_FILES[2], 3, 3)
    except Exception as err:
        return file_fail(OGLAP_REMOTE_FILES[2], 3, err)

    return {
        "profile": loaded["profile"],
        "localities": loaded["localities"],
        "data": loaded["data"],
        "checks": checks,
        "version_dir": str(version_dir),
        "error": None,
    }
