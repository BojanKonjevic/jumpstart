import os
import shutil
import sys

from zenit.cli.ui import step, success, warn
from zenit.core.context import Context


def apply(ctx: Context) -> None:
    step("Copying common files")
    common = ctx.zenit_root / "templates" / "_common"

    ctx.copy_file(common / "gitignore", ".gitignore")
    ctx.copy_file(common / "gitattributes", ".gitattributes")
    ctx.copy_file(common / "pre-commit-config.yaml", ".pre-commit-config.yaml")

    if sys.platform != "win32":
        is_nixos = os.path.isfile("/etc/NIXOS")

        if is_nixos:
            base_env = (common / "envrc").read_text()
            full_env = f"use nix shell.nix\n{base_env}"
            ctx.write_file(".envrc", full_env)
            ctx.copy_file(common / "shell.nix", "shell.nix")
            msg = (
                ".gitignore, .gitattributes, .pre-commit-config.yaml, .envrc, shell.nix"
            )
        else:
            ctx.copy_file(common / "envrc", ".envrc")
            msg = ".gitignore, .gitattributes, .pre-commit-config.yaml, .envrc"

        if shutil.which("direnv"):
            ctx.execute_command(["direnv", "allow"], check=False)
        else:
            hint = "direnv not found — .envrc copied but not activated."
            if is_nixos:
                hint += " You can also run 'nix-shell' to enter the environment."
            warn(hint)

        success(msg)
    else:
        success(".gitignore, .gitattributes, .pre-commit-config.yaml")
