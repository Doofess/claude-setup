# MCP presets

Project-scoped MCP servers. Nothing here loads globally; copy a preset into a
repo as `.mcp.json`, delete what that project does not use, and Claude Code asks
to approve it on the next start. Secrets come from environment variables
(`${DATABASE_URL}` etc.), never from the file.

| Preset | For | Servers |
| --- | --- | --- |
| `web.mcp.json` | Web apps | Supabase, Neon, Prisma, DBHub (any SQL), Vercel, Sentry, PostHog |
| `cluster.mcp.json` | Cluster backend | Kubernetes (read-only), Terraform, Grafana, Sentry, DBHub, docs.rs |

## Plugins to enable when a project of that kind starts

Skill-only plugins cost nothing until a skill fires, but they still add lines to
every session's skill list, so they stay off until needed.

```powershell
# Omnichannel frontend: web + React Native + Electron, one GraphQL layer
claude plugin enable expo@claude-plugins-official
claude plugin enable apollo-skills@claude-plugins-official

# Cluster backend
claude plugin enable terraform@claude-plugins-official
claude plugin enable streaming-skills-plugin@claude-plugins-official   # Kafka / Flink clients
claude plugin enable redis-development@claude-plugins-official
claude plugin enable semgrep@claude-plugins-official
claude plugin enable 42crunch-api-security-testing@claude-plugins-official  # OpenAPI audits
claude plugin enable grafana-mcp@claude-plugins-official   # or grafana-cloud-mcp
```

CLIs to install before the cluster project: `winget install Docker.DockerDesktop Kubernetes.kubectl Helm.Helm`.
