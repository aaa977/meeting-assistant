"""生成不包含密钥、缓存、日志和录音的项目发布包。"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "logs",
}
EXCLUDED_FILE_NAMES = {".coverage", ".env", "SHA256.txt"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".wav"}


class PackageError(Exception):
    """版本号、文件收集、ZIP 或校验文件生成失败。"""


def gather_files(root: Path) -> list[Path]:
    """收集发布文件，并排除运行数据、密钥、缓存和符号链接。"""
    root = Path(root).resolve()
    if not root.is_dir():
        raise PackageError(f"项目根目录不存在：{root}")

    files: list[Path] = []
    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        if any(part in EXCLUDED_DIRECTORIES for part in relative_path.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in EXCLUDED_FILE_NAMES:
            continue
        if path.suffix.casefold() in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def write_sha256(zip_path: Path) -> Path:
    """计算 ZIP 的 SHA256，并写入同目录 SHA256.txt。"""
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise PackageError(f"找不到发布包：{zip_path}")
    digest = hashlib.sha256()
    try:
        with zip_path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum_path = zip_path.parent / "SHA256.txt"
        checksum_path.write_text(
            f"{digest.hexdigest()}  {zip_path.name}\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        raise PackageError(f"无法生成 SHA256 校验文件：{error}") from error
    return checksum_path


def main(version: str) -> tuple[Path, Path]:
    """生成 meeting_assistant_<version>.zip 和 SHA256.txt。"""
    safe_version = version.strip()
    if not re.fullmatch(r"[0-9A-Za-z._-]+", safe_version):
        raise PackageError("版本号只能包含字母、数字、点、下划线和连字符。")

    root = Path(__file__).resolve().parent.parent
    dist_directory = root / "dist"
    zip_path = dist_directory / f"meeting_assistant_{safe_version}.zip"
    try:
        dist_directory.mkdir(parents=True, exist_ok=True)
        files = gather_files(root)
        with zipfile.ZipFile(
            zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for file_path in files:
                archive.write(file_path, file_path.relative_to(root).as_posix())
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageError(f"无法生成发布包：{error}") from error

    checksum_path = write_sha256(zip_path)
    return zip_path, checksum_path


if __name__ == "__main__":
    raise SystemExit("请通过主程序菜单 12 生成发布包。")
