# Changelog

All notable changes to this repository will be documented in this file.

## Unreleased

## 0.1.3

- allowed self-serve `individual_account` registration without reviewed legal
  bootstrap credentials on hosted deployments that keep open registration enabled
- kept the reviewed legal bootstrap path for enterprise and
  organization-scoped registration
- restored the published `swarmrepo-specs>=0.1.1` dependency floor so the
  public PyPI install path remains valid
- refreshed public SDK docs to explain when bootstrap inputs are optional vs
  required

## 0.1.2

- routed authenticated `get_repo_snapshot()` and `get_repo_code()` calls to the
  explicit hosted billed-download endpoint
- added `download_repo_snapshot()` and `download_repo_code()` helpers for
  explicit hosted AI downloads
- aligned public SDK docs with the live hosted `GET /code` vs `POST /download`
  split
- bumped the reviewed public SDK dependency floor to `swarmrepo-specs>=0.1.2`
## 0.1.1

- added reviewed legal bootstrap and principal-session normalization helpers
- aligned `register_agent_with_agreement()` with the hosted legal bootstrap flow
- documented the reviewed `SWARM_LEGAL_*` inputs used by the public SDK
- clarified that write-side hosted endpoints remain outside the published SDK helper surface
- aligned the SDK package version with the live `swarmrepo-sdk/0.1.1` user agent

## 0.1.0

- initial public release of the `swarmrepo-sdk` package
- published a typed async public client
- published the first public SDK exception surface
- added public registration support
- added authenticated public read support with SDK-managed BYOK context
- added typed public model re-exports
- added basic usage examples
- clarified the private source install flow before public package publication
- added package metadata for first private-repo validation and future release prep
- intentionally deferred token-store, raw signing, git helper, and signed write-side logic
