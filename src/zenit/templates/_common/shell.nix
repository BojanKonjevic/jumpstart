# Provide libstdc++.so.6 so the pre‑compiled greenlet wheel works.
{pkgs ? import <nixpkgs> {}}:
pkgs.mkShell {
  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:}$LD_LIBRARY_PATH"
  '';
}
