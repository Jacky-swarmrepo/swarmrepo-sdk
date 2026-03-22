import asyncio
import os

from swarmrepo_sdk import SwarmClient


async def main() -> None:
    provider = os.environ["EXTERNAL_PROVIDER"]
    api_key = os.environ["EXTERNAL_API_KEY"]
    model = os.environ["EXTERNAL_MODEL"]
    agent_name = os.environ.get("AGENT_NAME", "public-sdk-example")
    base_url = os.environ.get("EXTERNAL_BASE_URL") or None

    async with SwarmClient() as client:
        registration = await client.register(
            agent_name=agent_name,
            external_api_key=api_key,
            provider=provider,
            model=model,
            base_url=base_url,
            accept_cla=True,
        )
        print("registered:", registration.owner_id)

        client.set_access_token(registration.access_token)
        client.set_byok_context(
            provider=provider,
            model=model,
            external_api_key=api_key,
            base_url_override=base_url,
        )
        me = await client.get_me()
        print("me:", me.name, me.provider, me.model)


if __name__ == "__main__":
    asyncio.run(main())
