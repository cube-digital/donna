# Google integration setup: Gmail, Drive, and Pub/Sub for Cube-Context

This document is a practical reference for wiring Google Workspace sources into the Cube-Context ingestion service. It covers the three pieces of Google plumbing that an event-driven pipeline needs: Gmail label watching with Pub/Sub, Drive folder watching with push notifications, and Gmail filters with wildcard domain matching.

The document is opinionated about what's worth building for v1 versus what should wait. The short version: build webhooks where they meaningfully improve UX (Fathom, eventually Gmail), use polling where the latency cost is small (Drive, Gmail in v1). The longer version is below.

## A note on accuracy

Google's APIs evolve. OAuth scopes get refined, consent screen requirements shift, and minor details in the API surface change every few months. The patterns in this document were accurate at time of writing but should be verified against current docs before being committed to. Specifically worth checking:

- Current minimum-privilege OAuth scopes for Gmail watch and Drive watch
- Whether Gmail filters still support `*@domain.com` wildcard syntax identically in the API and the UI
- The current service account name for Pub/Sub grants (was `gmail-api-push@system.gserviceaccount.com`)
- Whether "Internal" apps still skip OAuth consent screen verification for Workspace users

These are ten-minute checks against the official documentation, not blockers — but worth doing before writing production code.

## The Google Cloud project (one-time setup)

Everything below requires a Google Cloud project. This is the same one-time setup whether you're going to use Gmail webhooks, Drive webhooks, or just programmatic API access.

The setup:

1. Go to `console.cloud.google.com` and create a project. Suggested name: `cube-context-ingestion`. Note the project ID — you'll need it for Pub/Sub topic names.
2. Enable the APIs you'll use: Gmail API, Drive API, and Cloud Pub/Sub API. Pub/Sub is only needed for Gmail watch (Drive uses simpler HTTP push, not Pub/Sub).
3. Configure the OAuth consent screen. For internal use within your Workspace, choose **Internal** as the user type. This skips Google's app verification process and limits authentication to users in your Workspace, which is what you want for an internal tool.
4. Create OAuth credentials. For a server-side ingestion service, "Web application" with a redirect URI you control is the right choice. For a CLI-driven setup where you authorize once and store the token, "Desktop app" also works.
5. Download the `credentials.json` file. This goes in your service's secrets directory — never in git.

### OAuth vs service account: which to use

You have two authentication patterns. Both work; they have different operational profiles.

**OAuth with refresh tokens.** Each user authorizes the service once. The service stores a long-lived refresh token and uses it to mint access tokens as needed. Setup is simple — visit a URL, click "allow," done. Refresh tokens last indefinitely as long as they're used periodically (Google may invalidate after ~6 months of inactivity).

This is the right choice for v1. It works for any Workspace, doesn't require admin access, and is the lowest-friction path.

**Service account with domain-wide delegation.** A service account impersonates users in your Workspace based on admin-configured permissions. Cleaner for unattended automation because there's no human authorization step. Requires Workspace admin access to configure (specifically, granting domain-wide delegation in the admin console).

Move to service accounts in v2 if managing OAuth tokens for multiple users becomes operational burden. For v1 with one or two ingestion accounts, OAuth is fine.

## Gmail: watching labels for project-relevant email

Gmail doesn't have "watch a label" as a direct primitive. It has `users.watch`, which subscribes you to changes in a mailbox (optionally filtered by labels), and delivers notifications via Pub/Sub. You then react to notifications by querying the mailbox for what actually changed.

This is more involved than the other two sources. For v1, IMAP polling against labeled threads is genuinely fine and dramatically simpler. The full Pub/Sub setup below is the production path; consider it the v2 design.

### Filters with wildcard domain matching

Before any watching, you need filters that label incoming project-relevant email. Gmail's filter system supports domain wildcards using `*@domain.com` syntax.

The UI approach: in Gmail web, Settings → Filters and Blocked Addresses → Create new filter.

For Acme:
- From: `*@acme.com OR *@acme-corp.com`
- Apply label: `vault/acme`
- (Optional) Skip inbox if you don't want these in the main view

For BetaHealth:
- From: `*@betahealth.de`
- Apply label: `vault/beta`

You can also use more complex criteria. Useful patterns:

- Multiple domains: `from:(*@acme.com OR *@acme-corp.com OR *@subsidiary.acme.com)`
- Specific people across domains: `from:(maria@*.com OR john@acme.com)`
- Subject-based routing: `subject:[acme]` to catch threads where the project tag is in the subject regardless of sender
- Exclude noise: add `-from:notifications@*.com` to skip automated notifications

The programmatic approach: manage filters as code via the Gmail API's `users.settings.filters` resource. Useful if you want filter definitions to live in `projects.yaml` and sync automatically when projects are added or removed.

```python
from googleapiclient.discovery import build

service = build('gmail', 'v1', credentials=user_credentials)

filter_body = {
    'criteria': {
        'from': '*@acme.com OR *@acme-corp.com'
    },
    'action': {
        'addLabelIds': ['Label_acme_id'],
        'removeLabelIds': ['INBOX']  # optional: skip inbox
    }
}

result = service.users().settings().filters().create(
    userId='me',
    body=filter_body
).execute()
```

To get label IDs, list labels first:

```python
labels = service.users().labels().list(userId='me').execute()
acme_label = next(l for l in labels['labels'] if l['name'] == 'vault/acme')
acme_label_id = acme_label['id']
```

Storing filter definitions per project in `projects.yaml` and running a sync script that ensures filters exist in each ingestion-account mailbox keeps this maintainable as projects come and go.

### Setting up Pub/Sub for Gmail watch

Gmail publishes notifications to a Cloud Pub/Sub topic, which then pushes to your webhook. The setup:

1. Create a Pub/Sub topic in your Google Cloud project. Name it `gmail-ingestion` or similar.
2. Create a push subscription on that topic. The push endpoint is your webhook URL: `https://ingest.cube-digital.io/webhook/gmail`.
3. Grant Gmail's service account permission to publish to the topic. The service account is `gmail-api-push@system.gserviceaccount.com`. Grant it `roles/pubsub.publisher` on the topic.

This grant is the step most people miss. Without it, Gmail can't publish notifications and watching silently fails.

Via `gcloud`:

```bash
gcloud pubsub topics create gmail-ingestion

gcloud pubsub topics add-iam-policy-binding gmail-ingestion \
    --member='serviceAccount:gmail-api-push@system.gserviceaccount.com' \
    --role='roles/pubsub.publisher'

gcloud pubsub subscriptions create gmail-ingestion-sub \
    --topic=gmail-ingestion \
    --push-endpoint=https://ingest.cube-digital.io/webhook/gmail
```

### Starting and renewing the watch

Once the Pub/Sub plumbing is in place, call `users.watch` once per user mailbox. Specify the labels you care about — this is how you scope the watch to project-relevant content instead of every email.

```python
service = build('gmail', 'v1', credentials=user_credentials)

# Get IDs of vault/* labels first
labels = service.users().labels().list(userId='me').execute()
vault_label_ids = [
    l['id'] for l in labels['labels']
    if l['name'].startswith('vault/')
]

watch_request = {
    'labelIds': vault_label_ids,
    'labelFilterAction': 'include',
    'topicName': 'projects/cube-context-ingestion/topics/gmail-ingestion'
}

response = service.users().watch(userId='me', body=watch_request).execute()

# Save this — you'll use it to fetch what changed since last notification
initial_history_id = response['historyId']
expiration = response['expiration']  # milliseconds since epoch
```

`labelFilterAction: 'include'` means "only notify me about changes to messages with these labels." This is the key to a useful watch — without it you get notifications for every message in the mailbox.

**Watches expire every 7 days.** This is the operational gotcha. Set up a daily cron job that re-calls `users.watch`. Google deduplicates, so calling it daily is safe and resilient. If the renewal fails, the watch lapses silently until manual intervention.

### Handling the push notification

When Gmail publishes a notification, your webhook receives a POST with a base64-encoded message. The decoded payload is minimal — just `emailAddress` and `historyId`. The actual message content isn't included.

```python
import base64
import json
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["POST"])
def gmail_webhook(request):
    body = request.data
    message = body["message"]

    # Decode the Pub/Sub message
    data = json.loads(base64.b64decode(message["data"]))
    email_address = data["emailAddress"]
    new_history_id = data["historyId"]

    # Look up the last history ID we processed for this mailbox
    last_history_id = state.get_last_history_id(email_address)

    # Fetch what changed since then
    service = build("gmail", "v1", credentials=get_credentials(email_address))
    history = service.users().history().list(
        userId="me",
        startHistoryId=last_history_id,
        historyTypes=["messageAdded"],
    ).execute()

    # Process each new message
    for record in history.get("history", []):
        for added in record.get("messagesAdded", []):
            message_id = added["message"]["id"]
            full_message = service.users().messages().get(
                userId="me",
                id=message_id,
                format="full",
            ).execute()
            process_message(full_message)

    # Save the new history ID for next time
    state.set_last_history_id(email_address, new_history_id)

    return Response(status=204)
```

This is the "Gmail tells you something changed, you ask what" pattern. Two API calls per notification batch, but Gmail batches notifications so you don't get one per message — you might get one notification covering several new messages.

### Reality check: when polling is enough

The Pub/Sub setup above is correct for production. For v1 with a few projects of email traffic, it's overkill. The simpler alternative:

- Set up filters in Gmail UI (one-time, takes minutes)
- Poll the mailbox via IMAP every 5-10 minutes
- Look for unread messages with `vault/*` labels
- Process and mark read

You lose true real-time (5-minute latency instead of seconds) and you skip Pub/Sub, OAuth complexity for Gmail, and 7-day watch renewals. The mental model is: "every 5 minutes, did anything new land in a labeled folder? Yes? Process it." Genuinely fine for low-to-moderate volume.

I'd start here and migrate to Pub/Sub only if latency becomes a real complaint.

## Drive: watching specific folders

Drive's push notifications are simpler than Gmail's — direct HTTP POSTs, no Pub/Sub middleware. The pattern is `files.watch`: you provide a webhook URL, Google POSTs when something changes.

### Setting up the watch

```python
import uuid
import time

service = build('drive', 'v3', credentials=user_credentials)

channel_body = {
    'id': str(uuid.uuid4()),                              # unique channel ID
    'type': 'web_hook',
    'address': 'https://ingest.cube-digital.io/webhook/drive',
    'token': 'shared-secret-for-verification',            # optional but recommended
    'expiration': int((time.time() + 7*24*3600) * 1000)   # 7 days, ms
}

response = service.files().watch(
    fileId='1abcDEF_acme_folder_id',
    body=channel_body
).execute()

# Save these — you need them to stop the watch later
channel_id = response['id']
resource_id = response['resourceId']
```

### Handling the notification

Drive POSTs a header-only notification. No body, just headers. You inspect `X-Goog-Resource-State` (created, updated, removed), `X-Goog-Resource-Id`, and your verification token.

```python
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response


@api_view(["POST"])
def drive_webhook(request):
    state = request.headers.get("X-Goog-Resource-State")
    resource_id = request.headers.get("X-Goog-Resource-Id")
    token = request.headers.get("X-Goog-Channel-Token")

    if token != "shared-secret-for-verification":
        raise PermissionDenied()

    # Look up which project this folder belongs to
    project = find_project_by_drive_resource_id(resource_id)
    if not project:
        return Response({"status": "ignored"})

    # Fetch current folder contents, compare with last-known state
    reindex_drive_folder(project)

    return Response(status=204)
```

### The folder watching caveat

`files.watch` on a single file notifies you on changes to that file. To watch a folder's contents (new files added, modifications inside), you have two paths:

**Path 1: Watch the folder file itself.** Drive treats folders as files. You get notifications when the folder's metadata changes — which includes when files are added or removed — but NOT when files inside the folder are modified.

**Path 2: Use the Changes API.** `changes.watch` with full Drive scope notifies you of any change in the user's Drive, and you filter by parent folder in your handler. Catches modifications to files inside watched folders, at the cost of higher notification volume and more processing.

For most ingestion use cases — primarily catching new files added to project folders, occasionally caring about modifications — neither approach is fully satisfying. The pragmatic v1 alternative is daily polling reindex of each project folder, which catches everything reliably without the watch complexity.

### Watch renewals

Same as Gmail: maximum 7 days. Daily cron renewal pattern. If a renewal fails, the watch lapses and changes aren't detected until manual intervention.

### Domain-wide visibility caveat

If you want to watch folders owned by other users in your Workspace, you need either:

- Domain-wide delegation (service account approach), letting one service identity impersonate any user
- Each user to authorize your app individually

There's no "watch any Drive folder I have access to" magic for an OAuth-based service running as a single identity. The folder must be accessible to the authenticated user.

For Cube-Context, the cleanest pattern is to have project Drive folders shared with a single ingestion account, and that account authorizes the service. Service account with domain-wide delegation is the equivalent production pattern but requires Workspace admin configuration.

### Pragmatic v1 for Drive

Skip `files.watch` entirely. Do a daily polling reindex:

```python
def reindex_project_drive(project):
    service = build('drive', 'v3', credentials=ingestion_credentials)

    query = f"'{project.drive_folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
        pageSize=1000
    ).execute()

    write_drive_index(project, results.get('files', []))
```

Run every 6 hours via cron. Latency: at most a few hours from "file added" to "appears in vault index." For project documents this is genuinely fine — nobody is sitting there waiting for a Drive file to materialize in their Obsidian vault.

## Putting it together: what to build for v1

After walking through all three Google integration paths, the pragmatic v1 architecture:

**Fathom: native webhook.** Easiest, highest value, real-time meeting context. Set this up first.

**Gmail: filters in UI plus IMAP polling.** Configure filters with wildcard domain matching once. Poll labeled messages every 5-10 minutes via IMAP. Skip Pub/Sub, OAuth complexity, and watch renewals for v1.

**Drive: daily polling reindex.** Skip `files.watch`. Walk each project folder via the Drive API every 6 hours, update the index in the vault. Skip watch renewals entirely.

This gets you:

- One real webhook (Fathom) where it matters most
- No Google Cloud project complexity for v1
- No Pub/Sub setup, no watch renewals, no 7-day expiration tracking
- A working pipeline in a weekend instead of a week
- Clear migration path: upgrade Gmail to Pub/Sub if latency complaints arise, upgrade Drive to `files.watch` if 6-hour latency becomes painful

The full webhook architecture (Pub/Sub for Gmail, `files.watch` for Drive) is correct for production scale and for a multi-tenant system. For a single small Workspace with a handful of active projects, polling is honest and fine.

## Things to verify before writing production code

Before committing to specific implementation details, check current Google documentation for:

- Minimum OAuth scopes for `gmail.modify` (needed for watch) and `drive.readonly` (needed for folder access). Use the smallest scope that does the job.
- Whether Gmail filter `from:*@domain.com` syntax behaves identically in the API and the UI.
- Current service account name for Pub/Sub grants. Was `gmail-api-push@system.gserviceaccount.com`; verify.
- Whether `labelFilterAction` parameter is still the correct field name on the `watch` request body.
- Drive `changes.watch` vs `files.watch` semantics for folder modifications — Google has refined this over time.
- Current 7-day expiration maximum for both Gmail and Drive watches.

Each of these is a quick docs check. Worth doing before code, not after.

## Operational notes

A few things worth knowing once you have any of this running:

**Pub/Sub messages can be redelivered.** If your webhook returns a non-2xx response, or doesn't respond in time, Pub/Sub redelivers. Your handler must be idempotent — processing the same `historyId` twice should produce the same result, not duplicates.

**Drive watch notifications are also retried** on non-2xx responses, with backoff. Same idempotency requirement.

**Watch renewals can race with active watches.** When you call `users.watch` while a watch is already active, the previous watch is replaced. There can be a brief window where notifications are missed or duplicated. Handle by tracking history IDs carefully.

**Quotas matter.** Gmail API has per-user quotas (250 quota units per user per second, with different operations costing different amounts). Drive API has its own quotas. For a small team, you won't hit these, but bursts (initial backfill of historical email when setting up) can hit them. Implement backoff.

**OAuth refresh tokens can be invalidated.** If a user changes their password, revokes the app, or the token sits unused for ~6 months, it gets invalidated. Your service needs a graceful failure path that prompts re-authorization rather than silently breaking.

**Filters apply only to new mail by default.** When you create a filter via the UI or API, it applies to incoming mail going forward, not retroactively. To label historical messages matching the filter, run `users.messages.list` with the same query and apply the label in a batch.

## Migration path from v1 polling to v2 webhooks

When you're ready to upgrade from polling to webhooks (likely because latency becomes annoying or volume grows), the migration is incremental:

1. Set up the Google Cloud project and OAuth credentials (if not done).
2. Configure Pub/Sub for Gmail (topic, subscription, IAM grants).
3. Start the Gmail watch alongside the existing IMAP poller. Run both in parallel.
4. Verify webhook notifications match polling results for a few days.
5. Cut over: disable polling, rely on webhook.
6. Add the daily watch-renewal cron job.

Same pattern for Drive when ready: run `files.watch` alongside the daily polling reindex, verify, cut over.

This way you don't take downtime during migration, and you can roll back trivially if the webhook path has issues.

## Reference: minimal code for each path

The smallest reasonable code for each integration, for copy-paste reference. Adapt to your actual codebase structure.

### Gmail filter creation (programmatic)

```python
def ensure_filter(service, from_pattern: str, label_id: str):
    """Idempotent: creates filter if it doesn't exist."""
    existing = service.users().settings().filters().list(userId='me').execute()
    for f in existing.get('filter', []):
        if (f.get('criteria', {}).get('from') == from_pattern
            and label_id in f.get('action', {}).get('addLabelIds', [])):
            return f['id']

    new = service.users().settings().filters().create(
        userId='me',
        body={
            'criteria': {'from': from_pattern},
            'action': {'addLabelIds': [label_id]}
        }
    ).execute()
    return new['id']
```

### Gmail IMAP polling (v1 simple path)

```python
from imapclient import IMAPClient

def poll_gmail_labels(label_patterns: list[str]):
    with IMAPClient('imap.gmail.com', ssl=True) as client:
        client.login(EMAIL, APP_PASSWORD)  # use Workspace app password
        client.select_folder('INBOX')

        for label in label_patterns:
            # Gmail exposes labels via X-GM-LABELS
            messages = client.search([
                'X-GM-LABELS', label,
                'UNSEEN'
            ])
            for msg_id in messages:
                raw = client.fetch([msg_id], ['RFC822'])
                process_email(raw[msg_id][b'RFC822'])
                client.add_flags([msg_id], [b'\\Seen'])
```

### Drive folder polling (v1 simple path)

```python
def poll_drive_folder(folder_id: str) -> list[dict]:
    service = build('drive', 'v3', credentials=ingestion_credentials)

    results = []
    page_token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink, owners)",
            pageSize=100,
            pageToken=page_token
        ).execute()

        results.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return results
```

### Gmail watch (v2 webhook path)

```python
def start_gmail_watch(service, label_ids: list[str], topic: str):
    return service.users().watch(
        userId='me',
        body={
            'labelIds': label_ids,
            'labelFilterAction': 'include',
            'topicName': topic
        }
    ).execute()


def renew_all_watches():
    """Run daily via cron."""
    for user_credentials in get_all_authorized_users():
        service = build('gmail', 'v1', credentials=user_credentials)
        labels = service.users().labels().list(userId='me').execute()
        vault_label_ids = [
            l['id'] for l in labels['labels']
            if l['name'].startswith('vault/')
        ]
        try:
            response = start_gmail_watch(
                service,
                vault_label_ids,
                'projects/cube-context-ingestion/topics/gmail-ingestion'
            )
            log.info(f"Renewed watch for {user_credentials.email}, expires {response['expiration']}")
        except Exception as e:
            log.error(f"Failed to renew watch: {e}")
            alert_ops(f"Gmail watch renewal failed: {e}")
```

### Drive watch (v2 webhook path)

```python
def start_drive_watch(folder_id: str, webhook_url: str) -> dict:
    service = build('drive', 'v3', credentials=ingestion_credentials)
    return service.files().watch(
        fileId=folder_id,
        body={
            'id': str(uuid.uuid4()),
            'type': 'web_hook',
            'address': webhook_url,
            'token': WEBHOOK_VERIFICATION_TOKEN,
            'expiration': int((time.time() + 7*24*3600) * 1000)
        }
    ).execute()


def stop_drive_watch(channel_id: str, resource_id: str):
    service = build('drive', 'v3', credentials=ingestion_credentials)
    service.channels().stop(body={
        'id': channel_id,
        'resourceId': resource_id
    }).execute()
```

These are skeletons, not production code. Add error handling, retries with backoff, structured logging, and dedup based on your specific patterns. But the shape is correct and you can build from here.
