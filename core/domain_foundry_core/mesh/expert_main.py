"""CLI/module entrypoint for a single Domain Expert process."""

from __future__ import annotations

import os
import sys

from domain_foundry_core.mesh.expert import ExpertRunner
from domain_foundry_core.paths import Workspace, default_home


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    domain = args[0] if args else os.environ.get("DOMAIN_FOUNDRY_MESH_DOMAIN")
    if not domain:
        print("usage: python -m domain_foundry_core.mesh.expert_main <domain>", file=sys.stderr)
        return 2
    home = default_home()
    runner = ExpertRunner(domain=domain, workspace=Workspace(home))
    try:
        runner.run_forever()
    except KeyboardInterrupt:
        runner.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
