# Public repository privacy audit

[← Project overview](../README.md)

Audit date: **2026-10-23**.

## Scope and results

The original published history contains **6 commits and 26 distinct file blobs**,
through [`1d18479`](https://github.com/petrovichest/klipper-motor-music/commit/1d18479193148c5c03d9d3088b629a3dd4a48d1d).
The documentation/presentation update is also scanned before publication.

| Surface | Check | Result |
|---|---|---|
| Complete published Git history | Gitleaks 8.30.1, default rules, all refs, redacted output | No secrets detected. |
| Every historical file blob | Private IPv4 ranges, personal home paths, local hostnames, private keys, credential-bearing URLs, email addresses | No private machine details or personal contacts found. |
| Author and committer metadata | Every published commit | Public GitHub handle and GitHub noreply address only. |
| Public Actions logs | All 6 original workflow runs, 88 archive entries; local Gitleaks and private-detail scans | No secrets or private machine details detected. |
| Branches and tags | Public refs | One branch; no extra branches or tags at audit time. |
| Issues, releases, and uploaded Actions artifacts | Public GitHub API | None at audit time. |

The repository contains extension code, synthetic test configurations, generic
installation examples, documentation, and attributed upstream music blocks.
Actual printer configuration, device logs, environment files, SSH material,
private network addresses, and recordings are not included in the audited history.

## What remains public

The GitHub account name in repository/source URLs, copyright notices, and commit
metadata remains public. The commit email is a GitHub **noreply** address, not a
personal mailbox. The printer model used to describe compatibility is generic
hardware information; no serial number or network address is published.

No published history rewrite was needed. Scanner reports and downloaded workflow
logs were kept outside the repository. The added language buttons and banner
are local SVG assets; the CI badge is served by GitHub.

## Rechecking

With Gitleaks installed, scan the complete history and current files locally:

```bash
gitleaks git . --log-opts=--all --redact=100
gitleaks dir . --redact=100
git log --all --format='%h %an <%ae> | %cn <%ce>'
```

The ignore file also excludes common local printer data, environment files,
backups, and private-key filenames. Ignore rules and scanners are precautions,
not a guarantee against all possible personal information or future changes.
