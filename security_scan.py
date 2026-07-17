"""Static security scanner for candidate-submitted code.

pawscode executes user-submitted solutions with `python3` / `sqlite3`. Before
execution we scan for dangerous patterns (process spawn, eval/exec, network
access, filesystem destruction, secrets exfiltration). The scan has two jobs:

  1. BLOCK — refuse to execute code that could damage the host (rm -rf,
     os.system, arbitrary subprocess with shell, etc.).
  2. WARN  — surface risky-but-legal patterns (network calls, file reads)
     so the candidate (and the tutor) understand the blast radius.

We use Bandit for the heavy lifting plus a small curated deny/allow list for
interview-specific idioms (e.g. `sorted`, `list`, `dict` are fine; `eval` is not).
"""

import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from bandit.core import manager as bandit_manager
    from bandit.core import config as bandit_config
    _BANDIT_OK = True
except Exception:  # pragma: no cover — bandit optional in some envs
    _BANDIT_OK = False


@dataclass
class Finding:
    severity: str          # "BLOCK" | "HIGH" | "MEDIUM" | "LOW"
    rule: str              # short rule id
    message: str
    line: Optional[int] = None

    def as_dict(self):
        return {"severity": self.severity, "rule": self.rule,
                "message": self.message, "line": self.line}


# Patterns that must never reach the executor. These are checked with plain
# regex on the raw source so we don't depend on Bandit's AST for the hard no's.
BLOCK_PATTERNS = [
    (r"\bos\.system\s*\(",            "os-system",      "Spawns a shell process via os.system()"),
    (r"\bos\.popen\s*\(",             "os-popen",       "Opens a pipe to a shell via os.popen()"),
    (r"\bsubprocess\.",               "subprocess",     "Spawns subprocesses — can run arbitrary commands"),
    (r"\beval\s*\(",                  "eval",           "eval() executes arbitrary code from a string"),
    (r"\bexec\s*\(",                  "exec",           "exec() executes arbitrary code from a string"),
    (r"\b__import__\s*\(",            "dunder-import",  "Dynamic import via __import__()"),
    (r"compile\s*\(",                 "compile",        "compile() can build code objects from strings"),
    (r"\bctypes\.",                   "ctypes",         "ctypes gives raw C/FFI access to the host"),
    (r"\b os\.remove\b|\bos\.rmdir\b|shutil\.rmtree", "fs-destroy", "Deletes files/directories on the host"),
    (r"\bopen\s*\([^)]*,\s*['\"][^'\"]*w", "fs-write",  "Opens a file for writing on the host filesystem"),
]

# Patterns that are legal in an interview but worth flagging.
WARN_PATTERNS = [
    (r"\bsocket\.|\brequests\.|\burllib\.|\bhttplib2\b|\baiohttp\b", "network",    "Makes network calls"),
    (r"\bopen\s*\(|\bpathlib\b|\bos\.path\b|\bshutil\.",               "filesystem", "Reads/writes the local filesystem"),
    (r"\bgetenv\b|\bos\.environ",                                       "env-read",  "Reads environment variables (possible secret leak)"),
    (r"\bthreading\.|\bmultiprocessing\.|\basyncio\.",                  "concurrency", "Spawns threads/processes/event loops"),
    (r"\bpickle\.|\bshelve\.|\bmarshal\.",                              "deserialize", "Deserializes data — can execute code on load"),
]


def _regex_scan(code: str, patterns, severity: str) -> List[Finding]:
    findings = []
    for pat, rule, msg in patterns:
        for m in re.finditer(pat, code):
            line = code.count("\n", 0, m.start()) + 1
            findings.append(Finding(severity, rule, msg, line))
    return findings


def _bandit_scan(code: str) -> List[Finding]:
    """Run Bandit on the in-memory source; map its severities to ours."""
    if not _BANDIT_OK:
        return []
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            f.write(code)
        conf = bandit_config.BanditConfig()
        bm = bandit_manager.BanditManager(conf, "file")
        bm.discover_files([path])
        bm.run_tests()
        sev_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
        out = []
        for issue in bm.get_issue_list():
            sev = sev_map.get(getattr(issue, "severity", "LOW"), "LOW")
            # Bandit's "shell" / "code injection" tests are hard BLOCKs for us
            if issue.test_id in ("B602", "B604", "B606", "B607"):
                sev = "BLOCK"
            out.append(Finding(sev, issue.test_id, issue.text, issue.lineno))
        return out
    except Exception:
        return []
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def scan_code(code: str) -> List[Finding]:
    """Return all findings for a candidate submission, highest severity first."""
    findings: List[Finding] = []
    findings += _regex_scan(code, BLOCK_PATTERNS, "BLOCK")
    findings += _bandit_scan(code)
    findings += _regex_scan(code, WARN_PATTERNS, "MEDIUM")
    order = {"BLOCK": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    findings.sort(key=lambda f: order.get(f.severity, 9))
    # de-dup by (rule, line)
    seen = set()
    unique = []
    for f in findings:
        key = (f.rule, f.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


def has_blocker(code: str) -> Optional[Finding]:
    """Return the first BLOCK-level finding, or None if safe to run."""
    for f in scan_code(code):
        if f.severity == "BLOCK":
            return f
    return None


if __name__ == "__main__":
    sample = (
        "import os\n"
        "os.system('rm -rf /')\n"
        "x = eval(input())\n"
        "import requests\n"
        "requests.get('https://evil.com')\n"
    )
    for f in scan_code(sample):
        print(f"[{f.severity}] {f.rule} @ line {f.line}: {f.message}")
