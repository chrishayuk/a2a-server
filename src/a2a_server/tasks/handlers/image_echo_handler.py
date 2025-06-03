# a2a_server/tasks/handlers/image_echo_handler.py
from __future__ import annotations

"""Image-Echo handler (v1.3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Robustly echoes back **one** image (as base64) regardless of whether the
caller sends:

* `image_base64` → `{type:"image_base64", data:"<b64>"}`
* `image_file`   → `{type:"image_file", path:"./pic.png"}` **or** `{file:"./pic.png"}`
* `image_file`   → _same object_ but with a **`data`** key already holding the
  base64 string (A2A-CLI < 0.4 does this)
* `image_url`    → `{type:"image_url", url:"https://…"}`

If the handler can't load the image it now returns **TaskState.failed** with
`status.message` describing the root cause - visible in the CLI.
"""

import base64
from pathlib import Path
from typing import AsyncIterable, Optional, Tuple

import httpx
from a2a_json_rpc.spec import (
    Artifact,
    DataPart,
    Message,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from a2a_server.tasks.task_handler import TaskHandler


class ImageEchoHandler(TaskHandler):
    """Return the provided image untouched (base64)."""

    SUPPORTED_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"]

    # ------------------------------------------------------------------
    # TaskHandler interface
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return "image_echo"

    async def process_task(
        self,
        task_id: str,
        message: Message,
        session_id: Optional[str] = None,
    ) -> AsyncIterable[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
        # working …
        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.working), final=False)

        # ------------------------------------------------------------------
        # 1. dig through parts until we manage to obtain *bytes* ------------
        # ------------------------------------------------------------------
        img_bytes: Optional[bytes] = None
        fail_reason: Optional[str] = None

        for part in (message.parts or []):
            pdata = part.model_dump(exclude_none=True)
            ptype = (pdata.get("type") or "").lower()

            # -- explicit base64 blob --------------------------------------
            if "data" in pdata and (ptype in {"image_base64", "image_file", ""}):
                try:
                    try:
                        # permissive decode - tolerate newlines or missing padding
                        img_bytes = base64.b64decode(pdata["data"], validate=False)
                    except Exception:
                        # data:URI style? strip prefix if present and retry
                        cleaned = pdata["data"].partition(",")[2] if "," in pdata["data"] else pdata["data"]
                        img_bytes = base64.b64decode(cleaned, validate=False)
                except Exception as exc:  # noqa: BLE001
                    fail_reason = f"invalid base64 data ({exc})"
                break

            # -- URL --------------------------------------------------------
            if ptype == "image_url" and pdata.get("url"):
                img_bytes, fail_reason = await self._fetch_url(pdata["url"])
                break

            # -- Local file path -------------------------------------------
            if ptype in {"image_file", "image_path"} or (not ptype and pdata.get("file")):
                path = pdata.get("path") or pdata.get("file")
                if path:
                    try:
                        img_bytes = Path(path).expanduser().read_bytes()
                    except Exception as exc:  # noqa: BLE001
                        fail_reason = f"cannot read file {path!r} ({exc})"
                else:
                    fail_reason = "image_file part missing 'path'/'file' key"
                break

        # ------------------------------------------------------------------
        # 2. bail‑out on failure -------------------------------------------
        # ------------------------------------------------------------------
        if img_bytes is None:
            msg = TextPart(type="text", text=f"Image‑Echo failed: {fail_reason or 'no image supplied'}")
            status = TaskStatus(state=TaskState.failed)
            object.__setattr__(status, "message", Message(role=Role.agent, parts=[msg]))
            yield TaskStatusUpdateEvent(id=task_id, status=status, final=True)
            return

        # ------------------------------------------------------------------
        # 3. emit artifact & completion ------------------------------------
        # ------------------------------------------------------------------
        part = DataPart(type="image_base64", data=base64.b64encode(img_bytes).decode())
        artifact = Artifact(name="image_echo", index=0, parts=[part])
        yield TaskArtifactUpdateEvent(id=task_id, artifact=artifact)

        yield TaskStatusUpdateEvent(id=task_id, status=TaskStatus(state=TaskState.completed), final=True)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    async def _fetch_url(self, url: str) -> Tuple[Optional[bytes], Optional[str]]:
        try:
            async with httpx.AsyncClient(timeout=10) as cli:
                r = await cli.get(url)
                r.raise_for_status()
                return r.content, None
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)
