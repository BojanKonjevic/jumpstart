{
  description = "zenit — Python project scaffolder";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python312;
    in {
      devShells.default = pkgs.mkShell {
        packages = with pkgs; [
          docker
          python312
          uv
          ruff
          mypy
          just
          redis
          pnpm
          nodejs
        ];

        shellHook = ''
          export UV_PYTHON_DOWNLOADS=never
          export UV_PYTHON="${python}/bin/python3"
          # Install pip dependencies into .venv
          uv sync --quiet
          export PYTHONPATH="$PWD/src:$(echo $PWD/.venv/lib/python3.*/site-packages)"
        '';
      };
    });
}
