# Dashboards as code

Store exported SigNoz dashboard definitions as `*.json` files in this directory.
The apply script uses Ruby's standard library and targets Hubcap's pinned
**SigNoz v0.120.0**: the dashboard document must have `"version": "v5"`.

## Sample dashboard

[`sample-rails-overview.json`](sample-rails-overview.json) contains HTTP request
rate and p95 latency graphs, using server spans already sent to SigNoz. Its
`service` textbox defaults to `sykpatientsv2`; select another service in the
dashboard or edit the variable's `textboxValue` and `defaultValue` in the JSON.
Sampling affects these graphs because they reflect only ingested spans.

The sample is included in previews and applies like any other JSON file here.
Its ownership tag is `hubcap:sample-rails-overview`, separate from real dashboards.
Remove the file before applying if you do not want the sample created.

## Add or adopt a dashboard

1. Build or clone a dashboard in SigNoz.
2. Add exactly one unique ownership tag, such as `hubcap:rails-overview`, in the
   **UI before exporting**. This lets the first apply adopt the existing dashboard
   instead of creating another one.
3. Export its JSON into this directory, for example `rails-overview.json`.
4. Commit the definition after reviewing its queries, variables, and filters.

Keep the ownership tag unchanged when renaming a dashboard or file. Other tags
are allowed. Store the dashboard definition, not the API response wrapper:
`title`, `tags`, `widgets`, `layout`, `variables`, and `version` belong at the
top level. API IDs, timestamps, organization IDs, and creator metadata do not.
Do not remove individual panel IDs or query definitions from the export.

## Preview and apply

Create a dedicated service account with the **Editor** role in
**Settings → Service Accounts**. Generate an API key from its **Keys** tab.
Store these fields in the `hubcap/deployment` 1Password item:

| Field | Value |
|---|---|
| `SIGNOZ_URL` | `https://signoz.hubcap.lsepsi.hu` |
| `SIGNOZ_SERVICE_ACCOUNT_API_KEY` | The generated service account API key |

The script reads both fields directly using the 1Password CLI (`op`) and account
`my.1password.com`; enable desktop-app integration or sign in first.
The API access key is **not** the server's `SIGNOZ_TOKENIZER_JWT_SECRET`.

From the Hubcap repository root:

```bash
bin/signoz_dashboards          # read-only preview
bin/signoz_dashboards --apply  # create/update the planned dashboards
```

No URL or API-key environment variables are needed. Both values are only read
locally; they are not printed, added to the deployment secrets fetch, or injected
into any container. Never commit the API key's value.

The script validates every local definition before contacting SigNoz, then
matches dashboards by their `hubcap:*` ownership tags. It prints `CREATE`,
`UPDATE`, or `UNCHANGED`; only `--apply` performs writes. Repeated applies skip
unchanged definitions, and updates retain the existing dashboard ID and URL.
Unmanaged dashboards are left alone.

Duplicate ownership tags, malformed responses, locked dashboards requiring
updates, and API errors stop the operation. HTTPS verification remains enabled;
redirects are not followed and failed requests are not retried automatically.
Request failures print the HTTP status and full response body to stderr, including
malformed HTTP 200 responses. The API key is redacted if echoed in the body.
If no response was received, its status/body are reported as unavailable.
Response bodies may contain other sensitive data; treat error logs accordingly.

## Operating rules

- Run one apply at a time: the API does not enforce unique ownership tags.
- Removing a JSON file does **not** delete its dashboard. Delete explicitly in
  the UI when you intend to do so.
- Git is authoritative. UI edits may be overwritten at the next apply; export
  changes you want to keep. Experiment on clones without the ownership tag.
- Roll back by restoring an older JSON revision and applying again.
- Applies are not transactional. If a later write fails, earlier writes remain;
  fix the failure and rerun. After an ambiguous timeout, rerun the full command
  so it checks existing tags before attempting another create.
- This is the v1 dashboard API, not the v2/Perses schema. Migrate the script and
  exports before upgrading SigNoz to v0.135.0 or newer.

Run the mocked-API checks without credentials or a running SigNoz instance:

```bash
ruby test/signoz_dashboards_test.rb
```
