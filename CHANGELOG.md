# Changelog

All notable changes to this repository will be documented in this file.

## Unreleased

- started the `v0.2` legal and registration alignment pass
- added public registration-requirements, legal-acceptance, and registration-grant helpers
- moved primary registration imports onto the reviewed `swarmrepo-specs.registration` surface
- added a high-level `register_agent_with_agreement()` flow
- reframed README and examples away from the earlier CLA-first registration story
- kept `register(..., accept_cla=True, ...)` as a compatibility wrapper during the transition

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
