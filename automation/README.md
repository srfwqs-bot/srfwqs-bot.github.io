# Publish Automation

This folder stores generated publish automation state.

## Files

- `publish_queue.json`: new posts waiting for external distribution.
- `publish_status.json`: per-platform dispatch status for each post URL.

## Platform webhook env vars

Set these in GitHub Actions secrets to enable real delivery:

- `PUBLISH_GATEWAY_BASE_URL` (optional, e.g. `https://your-worker.workers.dev`)
- `BAIJIAHAO_PUBLISH_ENDPOINT`
- `BAIJIAHAO_PUBLISH_TOKEN` (optional)
- `TOUTIAO_PUBLISH_ENDPOINT`
- `TOUTIAO_PUBLISH_TOKEN` (optional)

If endpoint vars are missing, dispatcher keeps status as `queued` and retries in later runs.

If `PUBLISH_GATEWAY_BASE_URL` is set, dispatcher auto-uses:

- `${PUBLISH_GATEWAY_BASE_URL}/publish/baijiahao`
- `${PUBLISH_GATEWAY_BASE_URL}/publish/toutiao`
