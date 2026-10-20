"""
Corre el harness oficial (parcial2-harness/, sin modificarlo) contra el sistema local.

    .venv/bin/python local_harness/run_local.py            # todo (R1-R12)
    .venv/bin/python local_harness/run_local.py -k backend # solo un archivo de pruebas

Usa las costuras que el propio harness expone en harness/registry.py: CONFIG_OVERRIDE (URLs
locales) y AWS_OVERRIDE (LocalAWS). El reporte queda en local_harness/report.md y report.json.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "parcial2-harness")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HARNESS)
sys.path.insert(0, HERE)

import pytest  # noqa: E402
import yaml  # noqa: E402

from harness import registry  # noqa: E402
from local_aws import LocalAWS  # noqa: E402


def main(argv):
    with open(os.path.join(HERE, "config.local.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["cost_projection_file"] = os.path.join(ROOT, cfg["cost_projection_file"])
    registry.CONFIG_OVERRIDE = cfg
    registry.AWS_OVERRIDE = LocalAWS(os.path.join(ROOT, "data", "lake"), cfg["aws"]["tables"],
                                     os.path.join(HERE, "simulated_deployment.yaml"))
    os.environ["HARNESS_REPORT"] = os.path.join(HERE, "report")
    os.chdir(HARNESS)
    return pytest.main(["-c", os.path.join(HARNESS, "pytest.ini"), "--rootdir", HARNESS, "-q", *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
