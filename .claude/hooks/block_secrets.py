import sys, json, re

payload = json.load(sys.stdin)
tool = payload.get('tool_name', '')
inp = json.dumps(payload.get('tool_input', ''))

# Filename-based: catches direct reads/greps/shell access to known secret-shaped paths.
sensitive = [
    r'\.env', r'\.env\.', r'.*\.env$',
    r'.*\.pem$', r'.*\.key$', r'.*\.cert$', r'.*\.crt$',
    r'secrets\.json', r'credentials\.json',
    r'\.aws/credentials', r'\.ssh/'
]

# Shape-based (Bash only): catches commands that resolve and print secret VALUES without
# ever mentioning a secret filename in the command text itself -- e.g. `docker compose
# config` prints every env_file:-resolved value to stdout even though the command line
# never says ".env" (the reference lives inside docker-compose.yml). The filename list
# above can't catch this class at all; this is a second, independent check, matched
# against the raw command string (not the JSON-dumped payload) so position anchors like
# ^ and shell separators actually mean what they look like they mean.
risky_shapes = [
    r'docker[- ]compose\b[^\n]*\bconfig\b',
    r'\bprintenv\b',
    r'docker\s+inspect\b',
    r'docker\s+exec\b[^\n]*\benv\b',
    r'(^|[;&|]\s*)env(\s|$)',
]

if tool in ('Read', 'Bash', 'Grep'):
    for pattern in sensitive:
        if re.search(pattern, inp):
            print(f'BLOCKED: attempt to access sensitive file matching {pattern}', file=sys.stderr)
            sys.exit(1)

if tool == 'Bash':
    command = payload.get('tool_input', {}).get('command', '')
    for pattern in risky_shapes:
        if re.search(pattern, command):
            print(f'BLOCKED: command shape {pattern} can print resolved secret values', file=sys.stderr)
            sys.exit(1)

sys.exit(0)
