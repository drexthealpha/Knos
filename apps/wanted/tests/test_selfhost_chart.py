"""The self-host bundle (deploy/selfhost): the Helm chart renders (helm template, when helm is installed), refuses a
mainnet cluster, keeps secrets out of values, and the compose file runs the app beside SAML Jackson."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "deploy" / "selfhost" / "knos"
HELM = os.environ.get("KNOS_HELM") or shutil.which("helm")


def test_values_hold_no_secret_and_compose_has_both_services():
    v = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert v["cluster"] == "devnet" and v["replicaCount"] == 1
    flat = (CHART / "values.yaml").read_text(encoding="utf-8")
    for word in ("BEGIN PRIVATE", "sk_live", "QLOO_API_KEY=sk"):
        assert word not in flat
    c = yaml.safe_load((ROOT / "deploy" / "selfhost" / "compose.yaml").read_text(encoding="utf-8"))
    assert set(c["services"]) == {"knos", "sso"} and c["services"]["knos"]["build"]["dockerfile"] == "apps/wanted/Dockerfile"
    assert c["services"]["sso"]["image"].startswith("docker.io/boxyhq/jackson:")


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_helm_template_renders_and_refuses_mainnet():
    out = subprocess.run([HELM, "template", "t", str(CHART), "--set", "sso.enabled=true", "--set", "ingress.enabled=true"],
                         capture_output=True, text=True, check=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    kinds = sorted(d["kind"] for d in docs)
    assert kinds == ["Deployment", "Deployment", "Ingress", "PersistentVolumeClaim", "Service", "Service"]
    app = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-knos")
    env = {e["name"]: e.get("value") for e in app["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["KNOS_CLUSTER"] == "devnet" and env["KNOS_SSO_URL"].startswith("https://")
    bad = subprocess.run([HELM, "template", "t", str(CHART), "--set", "cluster=mainnet"], capture_output=True, text=True,
                         env={**os.environ, "HELM_DEBUG": "0"})
    assert bad.returncode != 0 and "devnet or localnet only" in bad.stderr
