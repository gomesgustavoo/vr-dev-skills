"""Pre-publish checks for this repo: no secrets, no personal paths or addresses, valid skills.

    python tools/check_repo.py              # exit 0 = clean, 1 = findings (printed as file:line: why)

Checks:
  - secrets: private keys, cloud/API tokens (AWS, GitHub, Google, Slack, OpenAI/Anthropic-style),
    JWTs, bearer tokens and password/secret/token assignments with a literal value;
  - personal data: user-profile paths with a real user name, private IPv4 addresses, e-mail
    addresses (noreply / example domains allowed), and every term in the git-ignored file
    `.private-terms` (one per line: your user name, device serials, internal host names, client
    project names...). Keep that file local; it is in .gitignore so the list itself never ships;
  - skills: every skills/<name>/SKILL.md has YAML front matter whose `name` equals the folder,
    a description, description <= 1536 characters, and the file stays under 500 lines;
  - every .json parses and every .py compiles; the plugin + marketplace manifests agree on the
    plugin name.
Stdlib only, Python 3.10+.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "out", "node_modules", ".venv"}
TEXT_EXT = {".md", ".py", ".ps1", ".sh", ".cs", ".json", ".yml", ".yaml", ".txt", ".svg", ".html", ".toml", ".cfg"}

SECRETS = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "GitHub token"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "Google API key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{24,}\b"), "API secret key (sk-...)"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), "JWT"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{24,}"), "bearer token"),
    (re.compile(r"""(?ix)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)
                     \s*[:=]\s*["'][^"'\s<>{}$]{8,}["']"""), "credential assignment"),
    (re.compile(r"\bOC\|[0-9]{10,}\|[0-9a-f]{20,}"), "Meta/Oculus app access token"),
]
PERSONAL = [
    (re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!<|%|\$|\{|you\b|me\b|Public\b|Default\b|USERNAME\b|name\b|user\b)[A-Za-z0-9._-]+"),
     "user-profile path with a real user name (use %USERPROFILE%, ~ or a placeholder)"),
    (re.compile(r"/(?:home|Users)/(?!<|\$|\{|you\b|me\b|user\b|runner\b)[a-z0-9._-]{3,}/"), "home path with a real user name"),
    (re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "private IPv4 address"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@(?!(?:users\.noreply\.github\.com|noreply\.|example\.(?:com|org)|anthropic\.com\b))"
                r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "e-mail address"),
]
ALLOW_LINE = re.compile(r"check_repo:\s*allow")   # put "check_repo: allow" on a line to accept a deliberate hit


def private_terms():
    path = os.path.join(ROOT, ".private-terms")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [t.strip() for t in f if t.strip() and not t.startswith("#")]


def files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def front_matter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    fm = {}
    for line in text[3:end].strip().splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            fm[k.strip()] = v.strip()
    return fm


def main():
    findings = []
    terms = private_terms()
    term_res = [(re.compile(re.escape(t), re.I), t) for t in terms]
    for path in files():
        r = rel(path)
        if r == ".private-terms":
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in TEXT_EXT:
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except UnicodeDecodeError:
            findings.append((r, 0, "not UTF-8 text"))
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if ALLOW_LINE.search(line):
                continue
            for rx, why in SECRETS + PERSONAL:
                if rx.search(line):
                    findings.append((r, n, why + ": " + rx.search(line).group(0)[:60]))
            for rx, term in term_res:
                if rx.search(line):
                    findings.append((r, n, "private term from .private-terms"))
        if ext == ".json":
            try:
                json.loads(text)
            except ValueError as e:
                findings.append((r, 0, "invalid JSON: %s" % e))
        if ext == ".py":
            try:
                compile(text, path, "exec")   # syntax only: nothing is imported or written
            except SyntaxError as e:
                findings.append((r, e.lineno or 0, "does not compile: %s" % e.msg))

    skills_dir = os.path.join(ROOT, "skills")
    for name in sorted(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else []:
        sk = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.isfile(sk):
            findings.append(("skills/" + name, 0, "no SKILL.md"))
            continue
        text = open(sk, encoding="utf-8").read()
        fm = front_matter(text)
        if fm is None:
            findings.append((rel(sk), 1, "no YAML front matter"))
            continue
        if fm.get("name") != name:
            findings.append((rel(sk), 2, "front matter name %r != folder %r" % (fm.get("name"), name)))
        desc = fm.get("description", "")
        if not desc:
            findings.append((rel(sk), 3, "no description"))
        if len(desc) + len(fm.get("when_to_use", "")) > 1536:
            findings.append((rel(sk), 3, "description is %d chars (> 1536 gets truncated)" % len(desc)))
        lines = text.count("\n") + 1
        if lines >= 500:
            findings.append((rel(sk), 0, "%d lines (keep SKILL.md under 500; move detail to references/)" % lines))

    try:
        plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
        market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
        names = [p.get("name") for p in market.get("plugins", [])]
        if plugin.get("name") not in names:
            findings.append((".claude-plugin/marketplace.json", 0, "no plugin entry named %r" % plugin.get("name")))
    except (OSError, ValueError) as e:
        findings.append((".claude-plugin", 0, "manifest unreadable: %s" % e))

    for r, n, why in findings:
        print("%s:%s: %s" % (r, n, why))
    print("check_repo: %s (%d finding(s)%s)" % ("FAIL" if findings else "OK", len(findings),
                                                 ", %d private term(s) checked" % len(terms) if terms else
                                                 ", no .private-terms file"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
