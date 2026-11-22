# guard.ps1 - Cursor security hook (beforeShellExecution / beforeMCPExecution)
# Policy source of truth: AGENTS.md. This script is a safety net, not the policy.
#
# Decisions:
#   deny  - direct network / data-transmission clients (curl, wget, ssh, ...)
#   ask   - dependency downloads, git network ops, paths outside the project
#   allow - everything else
# Fail-safe: unreadable input => exit 2, which blocks the action.
$ErrorActionPreference = 'Stop'
$PROJECT_ROOT = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
} catch {
    exit 2
}

function Reply($permission, $userMsg, $agentMsg) {
    $out = @{ continue = $true; permission = $permission }
    if ($userMsg) { $out.user_message = $userMsg }
    if ($agentMsg) { $out.agent_message = $agentMsg }
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Compress -Depth 5))
    exit 0
}

# --- MCP tool calls (beforeMCPExecution payload has tool_name) ---
if ($payload.PSObject.Properties.Name -contains 'tool_name') {
    $tool = [string]$payload.tool_name
    if ($tool -match '(?i)(fetch|download|upload|http|request|browser|navigate|crawl|scrape|search|send|post|mail)') {
        Reply 'deny' "MCP tool '$tool' is blocked by project security rules." `
            "AGENTS.md forbids internet access and data transmission without explicit user approval. The MCP tool '$tool' can reach the network. Stop and ask the user for approval."
    }
    Reply 'allow'
}

# --- Shell commands (beforeShellExecution payload has command) ---
$cmd = [string]$payload.command
if (-not $cmd) { Reply 'allow' }

# 1) Direct network / exfiltration clients -> deny (ceiling: keyword denylist;
#    encoded/dynamic commands evade string matching - AGENTS.md still applies).
#    The (?<![\w.]) lookbehind keeps path components like ".ssh" from matching.
$denyRe = '(?i)(?<![\w.])(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|nc|ncat|netcat|telnet|ssh|scp|sftp|ftp|bitsadmin)\b'
if ($cmd -match $denyRe) {
    Reply 'deny' 'Network command blocked by project security rules.' `
        "AGENTS.md forbids internet access and data transmission without explicit user approval. Blocked command: $cmd. Stop and ask the user for approval instead of working around this."
}

# 2) Dependency downloads and git network operations -> ask (user approval).
$askRe = '(?i)\b(git\s+push|git\s+clone|git\s+fetch|git\s+pull|npm|npx|pnpm|yarn|bunx?|pip3?|pipx|uv|poetry|conda|gem|cargo|composer|go\s+get|docker|podman|winget|choco|scoop|apt-get|apt|yum|dnf|brew)\b'
if ($cmd -match $askRe) {
    Reply 'ask' "This command needs your approval: $cmd" `
        "This command downloads dependencies or transmits data over the network. AGENTS.md requires explicit user approval. Ask the user before proceeding."
}

# 3) Absolute paths outside the project root -> ask. Paths may contain spaces
#    (the project root does), so tokens stop at command separators only and are
#    compared with an exact root prefix check (no regex boundary confusion).
$root = $PROJECT_ROOT.TrimEnd('\')
foreach ($m in [regex]::Matches($cmd, '[A-Za-z]:[\\/][^,;|]*')) {
    $p = $m.Value.TrimEnd("'", '"', ')', ']', '}')
    $inside = $p.Equals($root, 'OrdinalIgnoreCase') -or $p.StartsWith($root + '\', 'OrdinalIgnoreCase')
    if (-not $inside) {
        Reply 'ask' "Path outside the project needs your approval: $p" `
            "AGENTS.md rule 1: never access anything outside the project folder without explicit user approval. Project root: $root. Ask the user."
    }
}

# 4) Parent-directory traversal or home-directory references -> ask.
if ($cmd -match '(?<![\w.])\.\.([\\/]|[\s''"]|$)') {
    Reply 'ask' "Parent-directory traversal needs your approval: $cmd" `
        "AGENTS.md rule 1: never access anything outside the project folder without explicit user approval. Ask the user."
}
if ($cmd -match '(?i)(\$HOME|~[/\\]|%USERPROFILE%|%HOME%)') {
    Reply 'ask' "Home-directory access needs your approval: $cmd" `
        "AGENTS.md rule 1: never access anything outside the project folder without explicit user approval. Ask the user."
}

Reply 'allow'
