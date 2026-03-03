"""
=============================================================
PLUGVAULT — Plugin Review Agent
=============================================================
Agent autonome qui review les soumissions de plugins.

Verifie :
1. Structure du plugin (plugin.json, skills/, etc.)
2. Qualite du code (pas de malware, bonnes pratiques)
3. Documentation (README, descriptions)
4. Compatibilite Claude Code / Cowork

Usage:
    python plugin-review-agent.py <github_url>

Output: Rapport de review + decision (APPROVED / NEEDS_CHANGES / REJECTED)
=============================================================
"""

import anthropic
import json
import shutil
from pathlib import Path
from datetime import datetime

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-5-20250929"

# =============================================================
# REVIEW CRITERIA
# =============================================================

REVIEW_CRITERIA = """
## Plugin Review Checklist

### Structure (obligatoire)
- [ ] Contient .claude-plugin/plugin.json avec name, version, description
- [ ] Au moins 1 skill dans skills/ avec un SKILL.md
- [ ] Pas de fichiers binaires suspects
- [ ] Taille totale < 5MB

### Qualite
- [ ] SKILL.md bien structure avec instructions claires
- [ ] Pas de code malveillant
- [ ] Pas de credentials hardcodees
- [ ] Pas de dependances systeme lourdes

### Documentation
- [ ] README.md present et informatif
- [ ] Description claire de ce que fait le plugin
- [ ] Instructions d'installation si necessaire

### Compatibilite
- [ ] Compatible Claude Code ET/OU Cowork
- [ ] Skills utilisent le format standard (frontmatter + instructions)
"""

# =============================================================
# TOOLS
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

import subprocess as sp
import tempfile

temp_dir = None

def handle_clone_repo(url):
    global temp_dir
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
        return "Timeout: clone trop long"
    except FileNotFoundError:
        return "Erreur: git non installe"


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
        "eval(", "sk-ant-", "sk-", "AKIA",
        "password", "secret_key", "token =",
        "rm -rf",
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
# AGENT LOOP
# =============================================================

SYSTEM_PROMPT = """Tu es le Review Agent de PlugVault, un marketplace de plugins pour Claude.

## Ta mission
Analyser un plugin soumis et decider s'il peut etre publie sur le marketplace.

## Processus
1. Clone le repository
2. Liste tous les fichiers et verifie la structure
3. Lis plugin.json, SKILL.md, README.md
4. Verifie la securite de chaque fichier source
5. Evalue selon les criteres
6. Redige un rapport et donne ta decision

""" + REVIEW_CRITERIA + """

## Decisions
- APPROVED : Respecte tous les criteres, bonne qualite
- NEEDS_CHANGES : Prometteur mais necessite des modifications
- REJECTED : Problemes de securite ou format non respecte
"""


def review_plugin(github_url, max_iterations=15):
    messages = [{"role": "user", "content": "Review ce plugin : " + github_url}]

    for i in range(max_iterations):
        print("\n--- Iteration {}/{} ---".format(i + 1, max_iterations))

        response = client.messages.create(
            model=MODEL, max_tokens=4096,
            system=SYSTEM_PROMPT, tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            final = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final += block.text
            print("\nReview terminee apres {} iterations".format(i + 1))
            return final

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    print("  Tool: {} -> {}".format(
                        block.name,
                        json.dumps(block.input, ensure_ascii=False)[:80]
                    ))
                    r = process_tool_call(block.name, block.input)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": r
                    })
            messages.append({"role": "user", "content": results})

    return "Review interrompue: max iterations atteint"


def cleanup():
    global temp_dir
    if temp_dir and Path(temp_dir).exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("Nettoye: " + temp_dir)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python plugin-review-agent.py <github_url>")
        sys.exit(1)

    url = sys.argv[1]
    print("PlugVault Review Agent")
    print("Plugin: " + url + "\n")

    try:
        result = review_plugin(url)
        print("\n" + "=" * 60)
        print("RAPPORT DE REVIEW")
        print("=" * 60)
        print(result)
    finally:
        cleanup()
