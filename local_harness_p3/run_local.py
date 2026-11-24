"""
Corre el harness oficial del Parcial 3 (parcial3-harness-estudiantes/, sin modificarlo) contra el
sistema levantado en local (API + worker + Kinesis simulado con moto). Ver local_harness_p3/LEEME.md.

    python local_harness_p3/run_local.py              # R1-R12
    python local_harness_p3/run_local.py -k star      # solo un archivo de pruebas

Variables: PROBE_SALT (simula los eventos secretos del profesor), LOCAL_LAKE (carpeta del lago local del worker), BACKEND_URL, TEAM_SEED, AWS_ENDPOINT_URL.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "parcial3-harness-estudiantes")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HARNESS)
sys.path.insert(0, HERE)

import pytest  # noqa: E402

from harness import registry  # noqa: E402
from local_aws import LocalAWS  # noqa: E402


def main(argv):
    cfg = {
        "team_id": "local", "seed": int(os.environ.get("TEAM_SEED", "417")),
        "backend": {"base_url": os.environ.get("BACKEND_URL", "http://localhost:8000")},
        "aws": {"region": "us-east-1", "kinesis_stream": os.environ.get("KINESIS_STREAM", "airline-events"),
                "raw_events_uri": "s3://local/raw/events/", "athena_workgroup": "airline-p3",
                "athena_database": "airline_star"},
        "cost_projection_file": os.path.join(ROOT, "cost_projection.yaml"),
    }
    registry.CONFIG_OVERRIDE = cfg
    if os.environ.get("PROBE_SALT"):
        # Simula la corrida del profesor: mismos umbrales, otros eventos (probe_salt secreto).
        from harness.config import load_thresholds
        thr = load_thresholds()
        thr["probe_salt"] = int(os.environ["PROBE_SALT"])
        registry.THRESHOLDS_OVERRIDE = thr
    registry.AWS_OVERRIDE = LocalAWS(os.environ["LOCAL_LAKE"], "us-east-1", workgroup_cutoff=1_000_000_000)
    os.environ["HARNESS_REPORT"] = os.path.join(HERE, "report")
    os.chdir(HARNESS)
    return pytest.main(["-c", os.path.join(HARNESS, "pytest.ini"), "--rootdir", HARNESS, "-q", *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
