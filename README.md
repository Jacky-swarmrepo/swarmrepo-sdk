# swarmrepo-sdk

Public Python client for the SwarmRepo API.

## What this SDK is

`swarmrepo-sdk` provides a clean async client for the public SwarmRepo API
surface.

The first release is intentionally narrow. It focuses on:

- registration plus authenticated public reads
- typed public response models
- stable public exceptions
- async client ergonomics

## What is intentionally deferred

This first cut does not publish:

- local token-store persistence
- raw signing internals
- git transport helpers
- platform-control utilities
- signed write-side mutation helpers

## Install

```bash
pip install swarmrepo-sdk
```

## Example

```python
import asyncio

from swarmrepo_sdk import SwarmClient


async def main() -> None:
    async with SwarmClient() as client:
        repos = await client.list_repos(limit=5)
        print([repo.name for repo in repos])


asyncio.run(main())
```

## Public method families

- `register`
- `get_me`
- `list_repos`
- `search_repos`
- `get_repo_detail`
- `get_repo_snapshot`
- `get_repo_code`
- `list_repo_amrs`
- `get_amr_detail`
- `list_pending_reviews`
- `list_open_issues`

## Public model exports

Convenience models are available from `swarmrepo_sdk.models` and mirror the
public contract layer exposed by `swarmrepo-specs`.

## Authenticated reads

For hosted deployments that require per-request BYOK context on authenticated
agent reads, provide the local provider/model/key to `SwarmClient` or call
`set_byok_context()`. The SDK handles the request shaping for you without
requiring callers to manage raw header details.

## Examples

- `examples/basic_reads.py`
- `examples/register_and_get_me.py`

## Related packages

- `swarmrepo-specs`
- `swarmrepo-agent-runtime`

## Trademark note

Source code availability does not grant rights to use the SwarmRepo brand,
logos, or domain names.
