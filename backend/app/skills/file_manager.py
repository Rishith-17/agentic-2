"""File and folder operations with pathlib/shutil."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.skills.base import SkillBase


class FileManagerSkill(SkillBase):
    name = "file_manager"
    description = "Create, read, write, move, delete files and folders; organize directories."
    priority = 3
    keywords = ["file", "folder", "directory", "delete file", "read file", "write file", "move file", "rename", "organize"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_path",
                        "write_file",
                        "read_file",
                        "delete",
                        "rename",
                        "move",
                        "list_dir",
                        "organize_folder",
                    ],
                },
                "path": {"type": "string"},
                "content": {"type": "string"},
                "target": {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        root = Path(parameters.get("path") or parameters.get("root") or ".").expanduser().resolve()

        if action == "create_path":
            root.mkdir(parents=True, exist_ok=True)
            return {"message": f"Created path {root}"}

        if action == "write_file":
            p = Path(parameters["path"]).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            content = parameters.get("content") or ""
            p.write_text(content, encoding="utf-8")
            return {"message": f"Wrote {len(content)} chars to {p}"}

        if action == "read_file":
            p = Path(parameters["path"]).expanduser().resolve()
            text = p.read_text(encoding="utf-8", errors="replace")
            return {"message": f"Read {p}", "content": text[:50000]}

        if action == "delete":
            p = Path(parameters["path"]).expanduser().resolve()
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
            return {"message": f"Deleted {p}"}

        if action == "rename":
            src = Path(parameters["path"]).expanduser().resolve()
            dst = Path(parameters["target"]).expanduser().resolve()
            src.rename(dst)
            return {"message": f"Renamed to {dst}"}

        if action == "move":
            src = Path(parameters["path"]).expanduser().resolve()
            dst = Path(parameters["target"]).expanduser().resolve()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return {"message": f"Moved to {dst}"}

        if action == "list_dir":
            items = sorted(root.iterdir(), key=lambda x: x.name.lower())
            dirs_count = sum(1 for x in items if x.is_dir())
            files_count = sum(1 for x in items if x.is_file())
            names = [x.name + ("/" if x.is_dir() else "") for x in items[:200]]
            return {
                "message": f"Listing {root} ({len(items)} items total: {dirs_count} folders, {files_count} files)",
                "summary_text": f"Found {len(items)} items ({dirs_count} folders, {files_count} files) in {root}.",
                "items": names,
                "total_items": len(items),
                "total_folders": dirs_count,
                "total_files": files_count
            }

        if action == "organize_folder":
            # Move files into subfolders by extension
            for f in root.iterdir():
                if f.is_file():
                    ext = f.suffix.lower().lstrip(".") or "misc"
                    dest_dir = root / ext
                    dest_dir.mkdir(exist_ok=True)
                    shutil.move(str(f), str(dest_dir / f.name))
            return {"message": f"Organized files in {root} by extension"}

        return {"message": f"Unknown action {action}"}
