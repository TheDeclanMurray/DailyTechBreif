import sys, json, re

payload = json.load(sys.stdin)
tool = payload.get('tool_name', '')

if tool != 'Bash':
    sys.exit(0)

command = payload.get('tool_input', {}).get('command', '')

# Each pattern targets one destructive git operation that discards work with no
# undo (force-push overwrites remote history, reset --hard drops local commits/
# changes, branch -D force-deletes an unmerged branch, checkout -- / clean -f
# discard uncommitted work). Word-boundary/whitespace anchors so we don't false-
# positive on unrelated flags (e.g. --force-with-lease is deliberately exempted --
# it's the safe form of force-push).
DANGEROUS = [
    ('force-push (git push --force/-f)',
     r'\bgit\s+push\b(?:(?!--force-with-lease).)*?(?:--force(?!-with-lease)\b|(?:^|\s)-f(?:\s|$))'),
    ('git reset --hard',
     r'\bgit\s+reset\b[^\n]*--hard\b'),
    ('force branch delete (git branch -D)',
     r'\bgit\s+branch\b[^\n]*(?:(?:^|\s)-D(?:\s|$)|--delete\b[^\n]*--force\b)'),
    ('discard uncommitted changes (git checkout --)',
     r'\bgit\s+checkout\b[^\n]*(?:^|\s)--(?:\s|$)'),
    ('force-delete untracked files (git clean -f)',
     r'\bgit\s+clean\b[^\n]*(?:^|\s)-\w*f'),
]

for label, pattern in DANGEROUS:
    if re.search(pattern, command):
        print(
            f'BLOCKED: destructive git operation detected ({label}) in: {command}\n'
            'This command discards work with no undo. If you really mean it, run it '
            'directly in your own terminal outside Claude Code.',
            file=sys.stderr,
        )
        sys.exit(1)

sys.exit(0)
