# Access and trust model

## The core question

How do we share project context broadly enough that the execution team and management can collaborate effectively, while keeping commercial information — deal terms, pricing, strategic positioning — restricted to people whose roles require it?

This question shapes more architectural decisions than any other, because most failures in systems like this are access-control failures. The model below is the result of working through several alternatives and settling on the one that survives both day-to-day use and a serious security review.

## The model: two spaces, one axis of separation

We separate project context into two spaces:

The **team space** holds everything required to execute a project: technical scope, decisions, action items, architectural notes, research, client requirements expressed in technical terms, and progress updates. Every member of the execution team has access to every active project's team space. Members of management also have access. There is no per-project gating within the team space, because at our scale, cross-project visibility is a benefit (knowledge transfer, similar problems being solved by different teams) rather than a risk.

The **commercial space** holds everything in the team space *plus* the commercial wrapper: deal values, pricing decisions, contract terms, internal commercial strategy, competitive context, client relationship dynamics, and any other content that would be inappropriate for a new tech hire to read on their first day. Only co-founders and management have access.

This is one axis of separation, not three or four. We do not have per-project access tiers within the team space. We do not have per-individual access lists. We do not have a "junior dev tier" that sees less than "senior dev tier." Every additional tier multiplies the operational burden and the chance of misconfiguration. One tier suffices for our current size; we will revisit if and when we cross around fifteen people in the execution team.

## How this is enforced

Access enforcement happens at the repository level, not at the application level.

The team space is a private git repository named `cube-context-team`. Its GitHub access list (or self-hosted git equivalent) includes every member of the execution team plus management. Adding or removing access to this repo is the entire access-control workflow.

The commercial space is a separate private git repository named `cube-context-commercial`. Its access list is much smaller — co-founders and the management team. The list of people with access here is short enough that we can track it in our heads, and the cost of adding someone is a deliberate decision.

We do not rely on:

- Application-level filtering that decides at query time what a user can see
- LLM prompting that instructs an agent to "not mention" sensitive content
- Per-record tier tags inside a single shared store
- Encryption-at-rest with role-based decryption keys

These approaches have real uses in other systems, but for our scale and threat model they add complexity without making access more reliable. A repository ACL is enforced by the git host, is visible to everyone in the organization, and is the same primitive we already use for source code.

## What lives where

The clearest way to think about the two spaces is through a per-project view:

```
cube-context-team/
  projects/
    acme-corp/
      _brief.md             # technical scope and current state
      _status.md            # weekly auto-updated status
      meetings/             # team-distilled meeting summaries
      correspondence/       # project-relevant emails, team-distilled
      chats/                # Discord summaries, internal team channels
      docs/index.md         # links to Drive docs in the technical folder
      decisions.md          # append-only log of decisions
      open-questions.md     # current unresolved items

cube-context-commercial/
  projects/
    acme-corp/
      _deal.md              # HubSpot snapshot: stage, value, owner
      _strategy.md           # commercial strategy and positioning
      pricing.md            # rate cards, scope economics
      client-relationship.md # political context, relationship notes
      meetings-comm/        # full meeting summaries with commercial content
      correspondence-comm/  # commercial-flavored emails
      raw/
        fathom/             # full original transcripts
        gmail/              # full original email threads
        hubspot/            # raw deal snapshots
```

The team space contains only what an execution team member needs to do excellent work on the project. It does not contain monetary figures, deal stage information, contract terms, or commercial strategy. It also does not contain raw transcripts or emails — those live in the commercial space because they contain everything by definition.

The commercial space contains the team space's content (regenerated from the same raw artifacts), plus the commercial layer, plus the raw artifacts themselves. A person with commercial access has a complete view of every project.

## The role of the distiller

Distillation is where the access boundary is enforced in practice. When a Fathom transcript arrives, the pipeline does not store it in the team space and "trust" downstream consumers to filter. It runs the transcript through two distillation prompts that produce two different documents:

The **team distiller** produces a markdown summary intended for the team space. Its prompt instructs the LLM to extract technical decisions, scope discussions, action items, and open questions while explicitly excluding monetary amounts, deal stage mentions, pricing discussions, competitive commentary, and any other commercial content. The output reads as a coherent technical summary — it does not say "redacted" or otherwise signal that commercial content was omitted.

The **commercial distiller** produces a markdown summary intended for the commercial space. Its prompt is permissive — it captures the full meeting including all commercial nuance. This goes only to the commercial space.

The team distiller is the load-bearing piece of prompt engineering in the system. Its prompt is reviewable, version-controlled, and continuously refined. The distillers are documented in detail in the ingestion pipeline document.

## Defense in depth

Distiller filtering is not the only line of defense. We use three overlapping mitigations because no single one is perfect.

The **first line** is the architectural split: raw artifacts never land in the team space. Even if the team distiller's prompt fails completely, there is no raw transcript in the team vault for someone to read directly. The worst case from a distiller failure is a single distilled document that leaks information — bad, but bounded.

The **second line** is the distiller prompt itself, validated against past meeting transcripts and refined over the first month of operation. The prompt is instructed to write coherent summaries that read naturally even when commercial content is excluded, so the absence of commercial content does not itself leak its prior presence.

The **third line** is the leakage scanner. A scheduled job greps the team vault for patterns that should never appear: currency symbols (€, $, £), specific keywords ("margin", "rate card", "deal value", "pricing"), competitor names from our internal list, and numeric patterns that look like monetary figures. Hits are reported for review. Most will be false positives — "the rate of progress" is fine — but the system surfaces them so a human can confirm.

For the first month of operation, a fourth line is added: distilled team-space content goes through a pull request for human review before merging. This is human-in-the-loop validation while the prompt is being calibrated. After a month of evidence that the distiller is reliable, this gate is removed and the leakage scanner becomes the primary runtime check.

## The acceptable failure mode

We should be honest about what can still go wrong. The team-distiller prompt can produce a summary that mentions a deal value the team should not see. The leakage scanner can miss it because the value is phrased in a way that doesn't match any pattern. A human reviewer can approve the PR without noticing. The summary reaches the team vault, and a developer reads it.

This is the residual risk. It is small but not zero. The mitigations make it small. The alternative architectures we considered have larger residual risks for our scale, particularly anything that puts the full context in front of an LLM and asks the LLM to filter at output time. The two-vault architecture caps the worst case at "one document leaks" rather than "the entire context base is one prompt injection away from full exposure."

When a leak does happen — and we should expect it to happen at least once — the response is:

1. Revert the offending commit in the team vault
2. Audit the distiller prompt to understand why it produced the leak
3. Update the prompt and the leakage scanner to catch the pattern next time
4. Note the incident in the operational log

This is how all defense-in-depth systems work. We do not aim for a system that cannot fail; we aim for a system that fails small and recovers quickly.

## Onboarding and offboarding

Access provisioning is operationally simple because there are only two access lists:

To onboard a new team member: add them to `cube-context-team` on GitHub. If they're in management, also add them to `cube-context-commercial`. Send them a link to this documentation and the operational playbook.

To offboard a team member: remove them from both repositories. Rotate any secrets or API keys they had access to. Note the offboarding date in the operational log.

There is no per-project provisioning. There is no role-based access matrix to maintain. The two access lists are the entire access control surface.

## What happens with sensitive content outside the two spaces

Some content is too sensitive even for the commercial space. Examples include early-stage acquisition discussions, individual compensation, legal communications about disputes, and similar founder-level matters. This content stays out of Cube-Context entirely. It lives in restricted Drive folders, encrypted personal notes, or wherever the relevant individuals choose to keep it. Cube-Context is not a vault for everything sensitive; it is a vault for project context.

If a meeting is partly about a project and partly about founder-only matters, the human routing the transcript can decide to keep the transcript out of Cube-Context entirely and instead write a stripped meeting note manually. The system supports manual entries; it does not require everything to flow through automated ingestion.

## What the team can and cannot do

To set clear expectations for the execution team:

A developer working in the team space can see every active project's technical context, meeting summaries, decisions, and open questions. They can use Claude Code with this full context. They can plan tasks, write code, and ask questions that reference any project in the team space.

A developer cannot see deal values, pricing, commercial strategy, raw transcripts, or any commercial-tier content. If they need information that lives only in the commercial space — for example, the original wording of a client request from a transcript that was distilled with technical-only content — they ask a manager, who can read the raw transcript and answer.

This boundary is uncomfortable in some cases. It is the cost of the trust model. We accept it because the alternative — giving everyone access to everything — does not survive due diligence with our clients or with potential investors, and the alternative — building a complex tier-aware system — is not worth the engineering cost at our scale.

## Decisions to revisit

This model is right for now. It should be revisited when any of the following becomes true:

- The execution team exceeds approximately fifteen people, at which point cross-project visibility within the team space may start to feel like over-sharing
- A specific client contractually requires per-project access lists (some HealthTech clients may eventually require this)
- We onboard a client whose data sensitivity is high enough that even the team space is inappropriate for some content, requiring a third tier
- The leakage scanner shows enough false negatives that we no longer trust distillation alone

At each of these triggers, the model is revised, not the architecture. The architecture (separate repos for separate tiers) accommodates more tiers cleanly; we just don't pay for that complexity until we need it.
