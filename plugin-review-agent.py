"""
=============================================================
PLUGVAULT — Plugin Review Agent
=============================================================
Autonomous agent that reviews plugin submissions for the
PlugVault marketplace using Claude as the AI backbone.

Review process:
  1. Clone the submitted GitHub repository
  2. Inspect file structure and total size
  3. Read plugin.json, SKILL.md, README.md
  4. Run security checks on every source file
  5. Score the plugin against quality criteria
  6. Produce a structured report with a final decision

Decisions:
  APPROVED      — Meets all criteria, ready for marketplace
  NEEDS_CHANGES — Promising but requires fixes before publish
  REJECTED      — Security issues or fundamentally broken

Requirements:
  - Python 3.10+
  - anthropic SDK (pip install anthropic)  [optional]
  - git CLI available on PATH
  - ANTHROPIC_API_KEY environment variable set [optional]

Usage (legacy):
    python plugin-review-agent.py <github_url>

Usage (CLI):
    python plugin-review-agent.py --url <github_url> --output report.json

Behaviour:
  - If ANTHROPIC_API_KEY is set: runs Claude review (narrative + subjective score)
  - If not set: falls back to quality-scorer.py (objective score only)
  - If both available: merges scores 50/50
  - Output is always structured JSON when --output is used

Output: Markdown review report printed to stdout and saved to
        ~/Documents/PlugVault/reviews/
=============================================================
"""

import json
import os
import shutil
import subprocess as sp
import sys
import tempfile
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Optional Anthropic client
# ---------------------------------------------------------------------------

ANTHROPIC_AVAILABLE = False
client = None

try:
    import anthropic as _anthropic
    _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if _api_key:
        client = _anthropic.Anthropic()
        ANTHROPIC_AVAILABLE = True
except ImportError:
    pass

MODEL = "claude-sonnet-4-6"

# =============================================================
# REVIEW CRITERIA
# =============================================================

REVIEW_CRITERIA = """
## Plugin Review Checklist

### Structure (obligatoire — chaque item vaut 10 points, max 40)
- [ ] Contient .claude-plugin/plugin.json avec name, version, description
- [ ] Au moins 1 skill dans skills/ avec un SKILL.md
- [ ] Pas de fichiers binaires suspects (.exe, .dll, .so, .dylib)
- [ ] Taille totale < 5MB

### Qualite (chaque item vaut 10 points, max 40)
- [ ] SKILL.md bien structure avec instructions claires
- [ ] Pas de code malveillant (eval, exec, os.system avec input user, etc.)
- [ ] Pas de credentials hardcodees (API keys, tokens, passwords)
- [ ] Pas de dependances systeme lourdes ou dangereuses

### Documentation (chaque item vaut 5 points, max 15)
- [ ] README.md present et informatif (>100 mots)
- [ ] Description claire de ce que fait le plugin
- [ ] Instructions d'installation si necessaire

### Compatibilite (5 points)
- [ ] Compatible Claude Code ET/OU Cowork (skills au format standard)

## Scoring
- 90-100 : APPROVED — Excellent, pret pour le marketplace
- 60-89  : NEEDS_CHANGES — Prometteur, corrections necessaires
- 0-59   : REJECTED — Problemes majeurs

Tu DOIS donner un score numerique /100 dans ton rapport.
"""

# =============================================================
# TOOLS (for Claude agent loop)
# =============================================================

TOOLS = [
    {
        "name": "clone_repo",
        "description": "Clone un repository GitHub dans un dossier temporaire pour inspection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL du repository GitHub"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "list_files",
        "description": "Liste tous les fichiers d'un dossier avec leur taille.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin du dossier"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "read_file",
        "description": "Lit le contenu d'un fichier.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin du fichier"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "check_security",
        "description": "Verifie les patterns de securite suspects dans un fichier.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Chemin du fichier"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "save_review",
        "description": "Sauvegarde le rapport de review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string", "description": "Nom du plugin"},
                "decision": {
                    "type": "string",
                    "enum": ["APPROVED", "NEEDS_CHANGES", "REJECTED"],
                    "description": "Decision de review"
                },
                "report": {"type": "string", "description": "Rapport de review complet"}
            },
            "required": ["plugin_name", "decision", "report"]
        }
    }
]

# =============================================================
# TOOL HANDLERS
# =============================================================

temp_dir = None


def handle_clone_repo(url):
    global temp_dir
    if not url.startswith("https://github.com/"):
        return "Erreur: URL non valide (doit etre un repo GitHub)"
    temp_dir = tempfile.mkdtemp(prefix="plugvault-review-")
    try:
        result = sp.run(
            ["git", "clone", "--depth", "1", url, temp_dir],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return "Erreur de clone: " + result.stderr
        return "Repository clone dans " + temp_dir
    except sp.TimeoutExpired:
        return "Timeout: clone trop long (>60s)"
    except FileNotFoundError:
        return "Erreur: git non installe sur le systeme"


def handle_list_files(path):
    p = Path(path)
    if not p.exists():
        return "Dossier introuvable: " + path
    files = []
    total_size = 0
    for f in sorted(p.rglob("*")):
        if f.is_file() and ".git" not in f.parts:
            size = f.stat().st_size
            total_size += size
            rel = f.relative_to(p)
            files.append("  {} ({:,} bytes)".format(rel, size))
    header = "Total: {} fichiers, {:,} bytes ({:.1f} KB)\n".format(
        len(files), total_size, total_size / 1024
    )
    if total_size > 5_000_000:
        header += "ATTENTION: Plugin depasse 5MB!\n"
    return header + "\n".join(files[:100])


def handle_read_file(path):
    p = Path(path)
    if not p.exists():
        return "Fichier introuvable: " + path
    try:
        return p.read_text(encoding="utf-8")[:10000]
    except Exception as e:
        return "Erreur: " + str(e)


def handle_check_security(path):
    p = Path(path)
    if not p.exists():
        return "Fichier introuvable: " + path
    suspicious = [
        "eval(", "exec(", "os.system(", "subprocess.call(",
        "sk-ant-", "sk-", "AKIA", "ghp_", "glpat-",
        "password", "secret_key", "token =", "api_key",
        "rm -rf", "curl | bash", "wget | sh",
        "__import__", "importlib",
    ]
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        return "Fichier binaire ou illisible"
    findings = []
    for i, line in enumerate(content.split("\n"), 1):
        for pat in suspicious:
            if pat.lower() in line.lower():
                findings.append("  L{}: '{}' -> {}".format(i, pat, line.strip()[:80]))
    if findings:
        return "{} pattern(s) suspect(s):\n".format(len(findings)) + "\n".join(findings)
    return "OK - Aucun pattern suspect"


def handle_save_review(plugin_name, decision, report):
    output_dir = Path.home() / "Documents" / "PlugVault" / "reviews"
    output_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in plugin_name.lower())
    fp = output_dir / "review-{}-{}.md".format(safe, date)
    fp.write_text("# Review: {}\nDate: {}\nDecision: {}\n\n{}".format(
        plugin_name, date, decision, report
    ), encoding="utf-8")
    return "Review sauvegardee: " + str(fp)


def process_tool_call(name, inp):
    h = {
        "clone_repo": lambda: handle_clone_repo(inp["url"]),
        "list_files": lambda: handle_list_files(inp["path"]),
        "read_file": lambda: handle_read_file(inp["path"]),
        "check_security": lambda: handle_check_security(inp["path"]),
        "save_review": lambda: handle_save_review(
            inp["plugin_name"], inp["decision"], inp["report"]
        ),
    }
    return h.get(name, lambda: "Outil inconnu: " + name)()


# =============================================================
# AGENT LOOP (Claude-powered)
# =============================================================

SYSTEM_PROMPT = """Tu es le Review Agent de PlugVault, un marketplace de plugins pour Claude Code et Cowork.

## Ta mission
Analyser un plugin soumis et decider s'il peut etre publie sur le marketplace.

## Processus strict (suis cet ordre)
1. Clone le repository avec clone_repo
2. Liste tous les fichiers avec list_files pour verifier la structure et la taille
3. Lis les fichiers cles : .claude-plugin/plugin.json, les SKILL.md dans skills/, et README.md
4. Lance check_security sur CHAQUE fichier source (.py, .js, .ts, .sh, .md)
5. Evalue chaque critere du checklist et attribue les points
6. Calcule le score total /100
7. Redige un rapport structure en Markdown et donne ta decision avec save_review

## Format du rapport
```markdown
# Review: [nom du plugin]
## Score: XX/100
## Decision: APPROVED | NEEDS_CHANGES | REJECTED

### Structure (XX/40)
- ...

### Qualite (XX/40)
- ...

### Documentation (XX/15)
- ...

### Compatibilite (XX/5)
- ...

### Problemes trouves
- ...

### Recommandations
- ...
```

""" + REVIEW_CRITERIA + """

## Regles importantes
- Sois rigoureux : un plugin avec des credentials hardcodees est TOUJOURS REJECTED
- Sois precis : cite les fichiers et lignes problematiques
- Sois constructif : pour NEEDS_CHANGES, explique exactement quoi corriger
- A la fin de ton analyse, retourne un JSON avec: score, decision, summary (1 phrase)
"""


def _parse_score_from_report(report_text: str) -> int:
    """Extract numeric score from a markdown report."""
    m = re.search(r"##\s*Score\s*:\s*(\d+)", report_text, re.IGNORECASE)
    if m:
        return min(100, max(0, int(m.group(1))))
    m = re.search(r"(\d+)\s*/\s*100", report_text)
    if m:
        return min(100, max(0, int(m.group(1))))
    return 0


def _parse_decision_from_report(report_text: str) -> str:
    """Extract decision keyword from a markdown report."""
    for keyword in ("APPROVED", "NEEDS_CHANGES", "REJECTED"):
        if keyword in report_text:
            return keyword
    return "NEEDS_CHANGES"


def review_plugin_with_claude(github_url: str, max_iterations: int = 15) -> dict:
    """Run the full Claude-powered agent review. Returns structured dict."""
    if not github_url.startswith("https://github.com/"):
        return {"error": "URL must be a GitHub repository (https://github.com/...)"}

    messages = [{"role": "user", "content": "Review ce plugin : " + github_url}]
    final_text = ""

    for i in range(max_iterations):
        print("\n--- Iteration {}/{} ---".format(i + 1, max_iterations), file=sys.stderr)

        try:
            response = client.messages.create(
                model=MODEL, max_tokens=4096,
                system=SYSTEM_PROMPT, tools=TOOLS,
                messages=messages
            )
        except Exception as e:
            return {"error": "API error: {}".format(e)}

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    print("  Tool: {} -> {}".format(
                        block.name,
                        json.dumps(block.input, ensure_ascii=False)[:80]
                    ), file=sys.stderr)
                    try:
                        r = process_tool_call(block.name, block.input)
                    except Exception as e:
                        r = "Tool error: {}".format(e)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": r
                    })
            messages.append({"role": "user", "content": results})

    claude_score = _parse_score_from_report(final_text)
    decision = _parse_decision_from_report(final_text)

    # Try to extract JSON block from the report
    claude_summary = ""
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", final_text, re.DOTALL)
    if json_match:
        try:
            extracted = json.loads(json_match.group(1))
            claude_summary = extracted.get("summary", "")
            if not claude_score and extracted.get("score"):
                claude_score = int(extracted["score"])
        except Exception:
            pass

    return {
        "claude_score": claude_score,
        "decision": decision,
        "summary": claude_summary,
        "report": final_text,
    }


# =============================================================
# QUALITY SCORER FALLBACK
# =============================================================

import importlib.util as _ilu
import re

_SCORER_PATH = Path(__file__).parent / "scripts" / "quality-scorer.py"


def _load_quality_scorer():
    """Dynamically import quality-scorer.py."""
    spec = _ilu.spec_from_file_location("quality_scorer", _SCORER_PATH)
    if spec is None:
        return None
    mod = _ilu.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def run_quality_scorer(github_url: str) -> dict:
    """Run quality scorer. Returns scorer result dict or error dict."""
    mod = _load_quality_scorer()
    if mod is None:
        return {"error": "quality-scorer.py not found", "score": 0, "grade": "N/A"}
    try:
        return mod.score_plugin(github_url)
    except Exception as e:
        return {"error": str(e), "score": 0, "grade": "N/A"}


# =============================================================
# MERGE SCORES
# =============================================================

def merge_scores(quality_result: dict, claude_result: dict) -> dict:
    """Merge quality scorer (objective) and Claude (subjective) at 50/50."""
    q_score = quality_result.get("score", 0)
    c_score = claude_result.get("claude_score", 0)
    merged_score = round((q_score + c_score) / 2)

    grade_thresholds = [(85, "A"), (70, "B"), (55, "C"), (40, "D")]
    grade = "F"
    for threshold, g in grade_thresholds:
        if merged_score >= threshold:
            grade = g
            break

    return {
        "score": merged_score,
        "grade": grade,
        "quality_score": q_score,
        "claude_score": c_score,
        "breakdown": quality_result.get("breakdown", {}),
        "decision": claude_result.get("decision", "NEEDS_CHANGES"),
        "recommendation": quality_result.get("recommendation", ""),
        "review_summary": claude_result.get("summary", ""),
        "report_markdown": claude_result.get("report", ""),
        "details": quality_result.get("details", {}),
        "github_url": quality_result.get("github_url", ""),
        "scored_at": quality_result.get("scored_at", ""),
        "source": "merged",
    }


# =============================================================
# FULL REVIEW PIPELINE
# =============================================================

def full_review(github_url: str) -> dict:
    """Run full review pipeline. Returns structured result."""
    quality_result = run_quality_scorer(github_url)

    if ANTHROPIC_AVAILABLE:
        print("Running Claude review...", file=sys.stderr)
        claude_result = review_plugin_with_claude(github_url)

        if "error" in claude_result and not claude_result.get("report"):
            # Claude failed — fall back to quality scorer only
            print("Claude review failed, using quality scorer only.", file=sys.stderr)
            result = quality_result.copy()
            result["source"] = "quality_scorer"
            result["decision"] = _decision_from_score(quality_result.get("score", 0))
        else:
            result = merge_scores(quality_result, claude_result)
    else:
        result = quality_result.copy()
        result["source"] = "quality_scorer"
        result["decision"] = _decision_from_score(quality_result.get("score", 0))

    return result


def _decision_from_score(score: int) -> str:
    if score >= 85:
        return "APPROVED"
    elif score >= 55:
        return "NEEDS_CHANGES"
    return "REJECTED"


# =============================================================
# CLEANUP
# =============================================================

def cleanup():
    global temp_dir
    if temp_dir and Path(temp_dir).exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("Cleaned up: " + temp_dir, file=sys.stderr)


# =============================================================
# LEGACY MODE (backward compat — prints Markdown to stdout)
# =============================================================

def legacy_review(github_url: str):
    """Original behaviour: print Markdown report to stdout."""
    if ANTHROPIC_AVAILABLE:
        result = review_plugin_with_claude(github_url)
        report = result.get("report", "No report generated.")
        print("\n" + "=" * 60)
        print("RAPPORT DE REVIEW")
        print("=" * 60)
        print(report)
    else:
        result = run_quality_scorer(github_url)
        print("\n" + "=" * 60)
        print("QUALITY SCORE REPORT (no ANTHROPIC_API_KEY)")
        print("=" * 60)
        print(json.dumps(result, indent=2))


# =============================================================
# ENTRYPOINT
# =============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="PlugVault Plugin Review Agent"
    )
    # New CLI args
    parser.add_argument("--url", help="GitHub URL to review")
    parser.add_argument("--output", help="Output JSON file path")
    # Legacy positional arg
    parser.add_argument("github_url", nargs="?", help="GitHub URL (legacy positional)")
    args = parser.parse_args()

    url = args.url or args.github_url
    if not url:
        parser.print_help()
        sys.exit(1)

    print("PlugVault Review Agent")
    print("Plugin: " + url + "\n")

    try:
        if args.output:
            # Structured JSON mode
            result = full_review(url)
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"\nReport saved to: {output_path}", file=sys.stderr)
            # Also print summary to stdout
            print(json.dumps({
                "score": result.get("score"),
                "grade": result.get("grade"),
                "decision": result.get("decision"),
                "recommendation": result.get("recommendation"),
                "source": result.get("source"),
            }, indent=2))
        else:
            # Legacy mode — Markdown to stdout
            legacy_review(url)
    finally:
        cleanup()
