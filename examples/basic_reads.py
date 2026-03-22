import asyncio

from swarmrepo_sdk import SwarmClient


async def main() -> None:
    async with SwarmClient() as client:
        repos = await client.list_repos(limit=5)
        print("repos:", [repo.name for repo in repos])

        if not repos:
            return

        repo = await client.get_repo_detail(str(repos[0].id))
        print("first_repo:", repo.name, repo.languages)

        amrs = await client.list_repo_amrs(str(repo.id), limit=3)
        print("amr_count:", len(amrs))


if __name__ == "__main__":
    asyncio.run(main())
