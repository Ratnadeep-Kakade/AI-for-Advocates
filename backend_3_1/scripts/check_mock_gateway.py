"""Exercise every specialist route without calling a paid model API."""
import asyncio

from cicero.config import Settings
from cicero.models.contracts import ChatMessage, GenerationRequest, ModelRole
from cicero.models.gateway import ModelGateway


async def main() -> None:
    settings = Settings(_env_file=None)
    gateway = ModelGateway.from_settings(settings)
    specialist_roles = (
        ModelRole.DOCUMENT_INTELLIGENCE,
        ModelRole.LEGAL_RESEARCHER,
        ModelRole.ARGUMENT,
        ModelRole.COUNTERARGUMENT,
        ModelRole.EVALUATOR,
    )
    for role in specialist_roles:
        provider, model = gateway.route_for(role)
        if provider != "mock":
            raise SystemExit(
                f"{role.value} is routed to {provider}, not mock. "
                "This offline check is intended for the pre-GPU configuration."
            )
        result = await gateway.generate(
            GenerationRequest(
                role=role,
                messages=[
                    ChatMessage(role="user", content="Check the model gateway route."),
                ],
                max_output_tokens=64,
            )
        )
        print(f"{role.value}: provider={provider}, model={model}, response={result.text}")


if __name__ == "__main__":
    asyncio.run(main())
