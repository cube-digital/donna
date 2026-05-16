# Operational playbook

## What this document is

This is the day-to-day operational reference for running Cube-Context. It covers the routine tasks, the conventions the team must follow for the system to work, the procedures for common incidents, and the maintenance schedule.

This is a living document. As we learn what actually breaks and what actually needs attention, it grows.

## Ownership

- **Architecture and code**: Rares (or whoever inherits the engineering lead role)
- **Registry maintenance**: Andreea (or designated operational owner)
- **Access provisioning**: Co-founders (both repositories' GitHub admin)
- **Distiller prompt tuning**: Rares, with input from anyone who notices distillation issues
- **GDPR and client data requests**: Andreea coordinates with the requesting client

Every team member is responsible for following the conventions below. The owners handle exceptions and infrastructure.

## Conventions the team must follow

The system depends on a small set of team behaviors. Without these, routing accuracy drops and the system becomes less useful.

**Calendar invite naming.** When creating a meeting invite for a client project, include the project alias in brackets in the title: `[acme] Weekly sync`, `[acme] Architecture review`, `[beta] Kickoff`. This is the single most important convention. Fathom uses the meeting title for routing, and a missing tag means a transcript ends up in `unrouted/` requiring manual triage.

If you're invited to a meeting and the invite doesn't have the right tag, edit the title before the meeting starts.

**Gmail forwarding for project threads.** When you receive a project-relevant email thread you want preserved in the project context, forward it to the appropriate alias:

- `projects+<slug>@cube-digital.io` for technical/execution threads → lands in team vault
- `projects-comm+<slug>@cube-digital.io` for commercial threads → lands in commercial vault

For mixed threads (which are common): forward the whole thread to the commercial alias, and the distiller will produce a team-safe summary if there's technical content. Don't try to split a thread manually.

You do not need to forward every email, only those that contain context worth preserving — decisions, scope discussions, technical specs, client requests. Routine scheduling emails or one-line confirmations are noise.

**Discord channel naming.** Project channels follow the pattern `#<slug>-tech` (default, team space) or `#<slug>-comm` (commercial space). When creating a new project channel, use this pattern and update the registry. The bot routes based on channel ID, but the suffix convention makes it obvious to humans which space content lands in.

**Drive folder structure.** Each client project has a folder at `Drive/Projects/<Project Name>/` with subfolders `Tech/` and `Commercial/`. Tech-relevant docs go in `Tech/`. Commercial docs (proposals, contracts, pricing discussions) go in `Commercial/`. The indexer respects this split.

If you create a new Drive folder for a project, register it in the registry so the indexer picks it up.

**Don't put sensitive content in the wrong place.** If you accidentally drop a deal value into a team-vault meeting note (manually editing, not via distiller), revert it. If you see commercial content in the team vault that shouldn't be there, report it to Rares or Andreea immediately. The defense-in-depth is good but not infallible, and human awareness is part of it.

## Routine maintenance

### Daily (automatic)

Most daily work is automated. The cron jobs handle:

- HubSpot snapshot polling
- Drive folder scan for new/modified docs
- Discord daily summary batches
- Leakage scanner run on the previous day's team-vault commits

If everything is healthy, no human action is required daily. If a job fails, alerts fire (see Alerting below).

### Weekly (manual)

A weekly checklist for the operational owner (Andreea):

**Monday or Tuesday:**

- Triage `unrouted/` folders in both vaults. For each unrouted artifact, decide:
  - Add a registry entry if it's a new project not yet captured
  - Manually route via the CLI if the existing registry should have caught it (and update the registry to prevent recurrence)
  - Discard if it's noise
- Review the leakage scanner report from the past week. False positives are noted (so we can refine patterns). Real hits become prompt-engineering tickets.
- Quick scan of the team-vault `_status.md` files to see which projects look stale (no commits in 2+ weeks on an active project is a yellow flag).

**Friday:**

- Quick review of the week's distillation PRs (if any) that were approved or rejected.
- Note any team member friction with conventions (Gmail forwarding hard? Calendar tagging being missed?). These become items for the next team sync.
- Update the `_status.md` for projects that don't auto-generate it yet, by reading the week's meeting summaries.

### Monthly

- Review the registry for archived projects (those that ended). Move their folders to `archived/` in both vaults; update status in the registry.
- Review access lists on both repositories. Remove anyone who has left the team or no longer needs access.
- Review the distiller prompts. Are there patterns of issues that suggest prompt updates? Are there new exclusions we should add?
- Backup verification: confirm the nightly SQLite backup exists and is restorable.

### Quarterly

- Capacity review: how many projects, how many artifacts per day, how much vault size growth? Are we approaching the scale limits where we'd need to add infrastructure?
- Security review: any clients added strict data requirements? Any compliance changes (GDPR updates, new contractual obligations)?
- Retrospective on the system: what worked, what didn't, what should we change in the next quarter?

## Adding a new project

When a new client engagement starts:

1. Andreea adds a registry entry to `_registry.yaml` in the team vault and `_registry-commercial.yaml` in the commercial vault. Use the template at the top of each registry file.
2. Create initial folder structure in both vaults:
   - `cube-context-team/projects/<slug>/` with empty subfolders for `meetings/`, `correspondence/`, etc.
   - `cube-context-commercial/projects/<slug>/` with the same structure plus the commercial-specific files.
3. Write an initial `_brief.md` for the project. This is the most important file in the project's folder. It should answer: what is this project, who is the client, what is the technical scope, who on our side is involved, what is the current state, what are the key constraints. Two to three paragraphs is enough.
4. Set up the project's Drive folders with the `Tech/` and `Commercial/` substructure. Register the folder IDs.
5. If there's a Discord channel for the project, add it to the registry.
6. Add the project's calendar invite alias to the team's shared documentation so everyone knows the tag.
7. Commit and push both registry updates with a clear commit message.

The first meeting after a project is added produces the first auto-distilled meeting summary. If this looks wrong (project misrouted, distillation off), investigate immediately — early issues are easier to fix than late ones.

## Adding a team member

When someone joins the execution team:

1. A co-founder adds them to the `cube-context-team` GitHub repository as a reader (or writer if they'll be contributing to playbooks or briefs).
2. Send them links to this documentation set, particularly the access and trust model and this playbook.
3. Walk them through cloning the team vault and setting up Obsidian and Claude Code against it.
4. Show them the conventions: calendar tagging, Gmail forwarding, Discord naming. Make sure they understand the trust boundary (no commercial content in the team vault, ever).
5. Add them to the registry as appropriate (if they own specific projects).

If the new team member is in management:

1. Also add them to `cube-context-commercial`.
2. Walk them through the commercial vault structure.
3. Brief them on what they can and cannot share with the execution team.

## Removing a team member

When someone leaves or changes roles:

1. Remove their access from both repositories on the same day.
2. Rotate any shared secrets they had access to (API keys for the ingestion service, deploy keys, etc.).
3. If they had OAuth tokens active for Gmail label-based ingestion (Pattern 2), revoke those.
4. Note the offboarding in the operational log.

## Triaging unrouted artifacts

The `unrouted/` folders in both vaults contain artifacts that the router couldn't match to a project. They need weekly human review.

For each unrouted artifact:

1. Open the artifact and identify the project it should belong to.
2. If the project exists in the registry: figure out why routing failed. Was the calendar invite missing a tag? Was an attendee email not in the registry? Update the registry to prevent recurrence.
3. If the project doesn't exist in the registry: either add it (if it's a real project we should track) or discard the artifact.
4. Use the CLI to manually route the artifact: `cube-ingest reroute <unrouted-path> --project <slug> --space <team|commercial>`.
5. Verify the artifact is now correctly placed in the right vault.

If a specific source produces a lot of unrouted artifacts, investigate the source. The signal-to-noise ratio of ingestion should be high; persistent unrouted volume suggests a convention problem or a routing-logic gap.

## Handling distiller leakage

When the leakage scanner flags a team-vault distillation:

1. The artifact lands in a pull request rather than being auto-merged.
2. Review the PR. The PR description includes the scanner's findings.
3. Decide:
   - **False positive** (e.g., "the discount applies to academic licenses" — technical context, not a leak): merge the PR. Note the false positive pattern for future scanner refinement.
   - **Real leak** (the distiller actually included commercial content): close the PR without merging. Investigate why the distiller produced this output. Update the distiller prompt to prevent the pattern. Re-run distillation if useful, or write the team summary manually.
4. If the same pattern leaks repeatedly, the prompt has a structural problem. Address it directly rather than patching with scanner rules.

When a leak is detected after the fact (someone reads the team vault and notices commercial content):

1. Revert the offending commit in the team vault: `git revert <commit-sha>` and push.
2. Audit how the distiller produced this output.
3. Update the prompt and the scanner together.
4. Note the incident in the operational log with date, what leaked, root cause, and fix.

The point of the log is pattern recognition: if the same kind of leak happens twice, the architecture or the prompt has a problem that surface-level patches won't fix.

## GDPR and data deletion requests

When a client contact requests erasure or any client requests data deletion:

1. Andreea coordinates with the client to confirm scope: are they requesting deletion of a specific person's data, all their organization's data, a specific time range?
2. Identify all relevant artifacts in both vaults:
   - Search `_registry.yaml` and `_registry-commercial.yaml` for the contact's email
   - Search both vaults for the email, name, or any other identifying string
   - Check the `raw/` folder in the commercial vault for any artifact (transcripts, emails, snapshots) involving the contact
3. Delete the relevant content. For full per-person erasure, this includes:
   - Removing them from the registry's contacts list
   - Deleting raw artifacts they appear in
   - Editing distilled summaries to remove their name (this is manual work)
   - Removing them from any per-project notes that mention them
4. Force-push the deletion commits to remove the content from git history if the request requires it. Note that this is destructive; verify before doing it.
5. Update the state database to mark relevant artifact IDs as deleted (so they aren't re-processed).
6. Document the deletion in the operational log: what was deleted, when, by whom, on whose authority.
7. Send confirmation to the client.

If the client's contract requires deletion of meeting recordings or transcripts after a fixed period, a scheduled job enforces this. The schedule is configured per project in the commercial registry.

## Service incidents

### Ingestion service down

Symptoms: healthcheck endpoint not responding; no new commits to either vault.

Recovery:

1. SSH to the host or check Cloud Run logs.
2. Look for the cause in the service logs (Loguru output).
3. Common causes and fixes:
   - Anthropic API rate limit or outage: wait and retry; consider lowering distillation concurrency
   - Git push failure (auth or network): check SSH keys and remote connectivity
   - SQLite lock contention: rare, but a restart resolves it
   - Out of memory or disk: scale up the VM or clean up old logs
4. Restart the service if needed: `docker-compose restart` on the host.
5. Verify webhooks are being received again (test with a manually-replayed Fathom email if needed).
6. For any artifacts missed during downtime: source-side retries (Fathom, HubSpot) usually cover this. For Discord, the bot's session-resume typically catches up. For anything that didn't come through, manually trigger ingestion.

### Vault corruption or accidental deletion

Symptoms: missing files, garbled commits, or "I just rm'd the wrong folder."

Recovery:

1. Don't push if the corruption hasn't been pushed yet.
2. If already pushed: revert the bad commit. `git revert <sha>` for a clean reversion, or `git reset --hard <good-sha>` followed by force push if the bad state must be wiped from history (rare).
3. Restore from any team member's local clone if the central repo is the corrupted one.
4. SQLite state may need restoration from the nightly backup if the ingestion service's state is also corrupted.

### Wrong content distilled to the wrong project

Symptoms: a meeting note for Acme appears in Beta's folder.

Recovery:

1. Revert the commits in both vaults.
2. Investigate the routing logic — why did it match the wrong project? Usually a registry alias collision or a calendar invite with the wrong tag.
3. Fix the underlying cause (correct the alias, fix the registry, retrain the team on the convention).
4. Manually re-route the artifact via the CLI.

## Monitoring and alerts

The minimal viable monitoring for v1:

- A `/health` endpoint on the ingestion service that returns 200 OK if the service is up and the registry loaded successfully
- A cron job (separate from the service) that hits the healthcheck every 5 minutes and alerts if it fails twice in a row
- Loguru output captured to a rolling log file; rotated daily, kept for 30 days
- The leakage scanner output reviewed weekly
- The `unrouted/` folder reviewed weekly

We do not have:

- A metrics database
- A dashboard
- Distributed tracing
- Real-time alerting on anything other than service down

These can be added if and when the system grows enough to need them. For now, the SQLite query "show me ingestion counts by source by day" plus the git log of commits is enough to understand what the system is doing.

## Documentation maintenance

This documentation set is itself living. When something changes — a new source is added, the access model evolves, a procedure is refined — the relevant document is updated and the change is committed with a clear message.

Major changes (new architecture decisions, new policy) are reviewed by a co-founder before merging. Minor changes (refining a procedure, fixing a typo) can be merged by anyone with write access.

The team should refer to this documentation rather than relying on individual memory or Slack history. If something is unclear in the documentation, that's a bug; file an issue or open a PR to clarify.

## Things to revisit periodically

Every quarter, look at:

- Is the operational ownership still right? Is one person carrying too much?
- Are the conventions being followed, or is the team working around them?
- Are the distiller prompts still appropriate, or have they drifted from current needs?
- Is the access model still appropriate, or have project sensitivities changed?
- Are there sources we should add or drop?
- Has any external client raised concerns about how their data is handled?

The right answer to most of these is "no change needed." The point of asking is to catch the cases where the answer is yes before the issue becomes a problem.
