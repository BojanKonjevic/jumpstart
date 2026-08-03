import os
import shutil
import sys

from zenit.cli.ui import step, success, warn
from zenit.core._filenames import COMMON_FILES
from zenit.core.context import Context
from zenit.core.filesystem import FileSystem

_COMMON_SOURCE_MAP: dict[str, str] = {
    ".gitignore": "gitignore",
    ".gitattributes": "gitattributes",
    ".pre-commit-config.yaml": "pre-commit-config.yaml",
}


def apply(ctx: Context, fs: FileSystem) -> None:
    step("Copying common files")
    common = ctx.zenit_root / "templates" / "_common"

    for dest_name in COMMON_FILES:
        src_name = _COMMON_SOURCE_MAP.get(dest_name)
        if src_name:
            fs.copy_file(common / src_name, dest_name)

    if sys.platform != "win32":
        is_nixos = os.path.isfile("/etc/NIXOS")

        if is_nixos:
            base_env = (common / "envrc").read_text()
            full_env = f"use nix shell.nix\n{base_env}"
            fs.write_file(".envrc", full_env)
            fs.copy_file(common / "shell.nix", "shell.nix")
            msg = (
                ".gitignore, .gitattributes, .pre-commit-config.yaml, .envrc, shell.nix"
            )
        else:
            fs.copy_file(common / "envrc", ".envrc")
            msg = ".gitignore, .gitattributes, .pre-commit-config.yaml, .envrc"

        if shutil.which("direnv"):
            fs.execute_command(["direnv", "allow"], check=False)
        else:
            hint = "direnv not found - .envrc copied but not activated."
            if is_nixos:
                hint += " You can also run 'nix-shell' to enter the environment."
            warn(hint)

        success(msg)
    else:
        success(".gitignore, .gitattributes, .pre-commit-config.yaml")
