"""Two MCP tools that read, never write: one NEAR swarm job as the jobs contract on NEAR testnet holds it, and the
rules referee IRIS runs (knos.referee_rules) applied to one proof against one brief. No key, no signature, no money."""
from __future__ import annotations

import base64
import json
import re
import urllib.request

RPC = "https://rpc.testnet.near.org"
CONTRACT = "jobs.knos-swarm-1105.testnet"
EXPLORER = "https://explorer.testnet.near.org/accounts/"
_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
KINDS = ("checkrun", "observation", "oru")


def _view(method: str, args: dict, timeout: float = 20):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "query",
                       "params": {"request_type": "call_function", "finality": "final", "account_id": CONTRACT,
                                  "method_name": method, "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}}).encode()
    req = urllib.request.Request(RPC, body, {"Content-Type": "application/json", "User-Agent": "knos-mcp"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(str(out["error"].get("cause") or out["error"])[:200])
    return json.loads(bytes(out["result"]["result"]).decode() or "null")


def swarm_job(args: dict) -> dict:
    jid = str(args.get("id") or "")
    if not _ID.fullmatch(jid):
        raise ValueError("id: a job id such as job-1105164458 (letters, digits, '-', '_', '.'; at most 64)")
    try:
        job = _view("get_job", {"id": jid})
    except (OSError, RuntimeError) as why:
        raise ValueError(f"NEAR testnet did not answer ({str(why)[:120]}); try again in a minute") from None
    if job is None:
        return {"found": False, "id": jid, "contract": CONTRACT, "network": "testnet",
                "next": "check the id: the NEAR app at https://drexthealpha.github.io/Knos/near/ shows the latest job"}
    return {"found": True, "id": jid, "contract": CONTRACT, "network": "testnet", "job": job,
            "explorer": EXPLORER + CONTRACT, "money": "testnet tokens, not real money"}


def check_proof(args: dict) -> dict:
    from knos import ready, referee_rules
    brief, kind, proof = args.get("brief"), args.get("kind"), args.get("proof")
    if not isinstance(brief, dict) or not isinstance(brief.get("milestones"), list) or not brief["milestones"]:
        raise ValueError("brief: an object with milestones, each with key and verifier (as knos_ready returns it)")
    if kind not in KINDS:
        raise ValueError(f"kind: one of {', '.join(KINDS)}")
    if not isinstance(proof, (str, dict)):
        raise ValueError("proof: the check run, FHIR Observation (an object) or HL7 ORU message (text)")
    if kind == "checkrun" and isinstance(proof, dict) and "check_run" not in proof and ({"name", "conclusion"} & set(proof)):
        proof = {"check_run": proof}       # a bare check run, as an agent most often sends it: GitHub's webhook wraps it
    payload = proof if isinstance(proof, str) else json.dumps(proof)
    if len(payload) > 200_000:
        raise ValueError("proof: at most 200,000 characters")
    got = json.loads(referee_rules.decide(json.dumps(brief), kind, payload, ready.criteria_hash(brief)))
    return {**got, "referee": "the rules referee IRIS runs (knos.referee_rules), run on this server; nothing signed, no money moved"}


TOOLS = [
    {"name": "knos_near_swarm_job", "title": "One NEAR swarm job",
     "description": "Reads one job from the jobs contract on NEAR testnet (jobs.knos-swarm-1105.testnet): its bid, the "
                    "locked test's hash, which agent took it, what each submitted, and who was paid. Read only.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "maxLength": 64, "description": "the job id, such as job-1105164458"}},
                     "required": ["id"], "additionalProperties": False}},
    {"name": "knos_iris_check_proof", "title": "Check a proof as IRIS does",
     "description": "Applies the rules referee IRIS runs to one proof (a CI check run, a FHIR Observation or an HL7 ORU "
                    "message) against a brief's milestones, and returns met or not met per milestone with the reason. "
                    "Nothing is signed and no money moves.",
     "inputSchema": {"type": "object", "properties": {
         "brief": {"type": "object", "description": "the brief: {milestones: [{key, name, target, verifier}]}"},
         "kind": {"type": "string", "enum": list(KINDS), "description": "what the proof is"},
         "proof": {"type": ["object", "string"], "description": "the proof itself"}},
         "required": ["brief", "kind", "proof"], "additionalProperties": False}},
]
HANDLERS = {"knos_near_swarm_job": swarm_job, "knos_iris_check_proof": check_proof}
