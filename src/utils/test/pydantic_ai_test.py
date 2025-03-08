"""Example demonstrating how to use PydanticAI to create a simple roulette game.

Run with:
    uv run -m pydantic_ai_examples.roulette_wheel
"""

from __future__ import annotations as _annotations
import os
import asyncio
from dataclasses import dataclass
from typing import Literal
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from pydantic_ai import Agent, RunContext


# Define the dependencies class
@dataclass
class Deps:
    winning_number: int

## Define the OpenAI model
model = OpenAIModel(
    os.getenv('OPENAI_COMPATIBLE_REASONING_MODEL'),
    provider=OpenAIProvider(
        base_url=os.getenv('OPENAI_COMPATIBLE_BASE_URL'), api_key=os.getenv('OPENAI_COMPATIBLE_TOKEN')
    ),
)
#agent = Agent(model)


# Create the agent with proper typing
roulette_agent = Agent(
    model=model,
    deps_type=Deps,
    retries=3,
    result_type=bool,
    model_settings={'parallel_tool_calls': True},
    system_prompt=(
        'Use the `roulette_wheel` function to determine if the customer has won based on the number they bet on.'
    ),
    instrument=True,
)


@roulette_agent.tool
async def roulette_wheel(
    ctx: RunContext[Deps], square: int
) -> Literal['winner', 'loser']:
    """Check if the bet square is a winner.

    Args:
        ctx: The context containing the winning number.
        square: The number the player bet on.
    """
    return 'winner' if square == ctx.deps.winning_number else 'loser'


async def main():
    # Set up dependencies
    winning_number = 18
    deps = Deps(winning_number=winning_number)

    # Run some example bets using streaming
    async with roulette_agent.run_stream(
        'Put my money on square eighteen', deps=deps
    ) as response:
        result = await response.get_data()
        print('Bet on 18:', result)

    async with roulette_agent.run_stream(
        'I bet five is the winner', deps=deps
    ) as response:
        result = await response.get_data()
        print('Bet on 5:', result)


if __name__ == '__main__':
    asyncio.run(main())