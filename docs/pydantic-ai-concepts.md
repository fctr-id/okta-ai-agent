# Pydantic AI (v0.0.40) - LLM Code Generation Guide

This document provides information and examples for generating code using Pydantic AI, a Python agent framework for building production-grade applications with Generative AI.  It focuses on version 0.0.40.

## Core Concepts

Pydantic AI builds upon the Pydantic library, leveraging its data validation and type hinting capabilities to create structured, type-safe interactions with Large Language Models (LLMs). It aims to provide a developer experience similar to FastAPI, but for GenAI applications. Key features include:

*   **Type-safe Design:**  Uses Python type hints and Pydantic models for validation of inputs, outputs, and dependencies.  This helps prevent runtime errors.
*   **Model-Agnostic:** Supports multiple LLM providers, including OpenAI, Anthropic, Gemini (via Generative Language API and Vertex AI), Ollama, Groq, Mistral, and Cohere.  It also provides a simple interface for adding support to other models.
*   **Structured Responses:**  Uses Pydantic models to define and validate the structure of LLM outputs, ensuring consistency.
*   **Dependency Injection:**  Offers an optional dependency injection system to provide data and services to agent's system prompts, tools, and result validators. This is useful for testing.
*   **Function Tools:**  Allows agents to call external functions (tools) to retrieve additional information or perform actions, extending the capabilities of the LLM.
*   **Streamed Responses:** Supports streaming LLM outputs with immediate validation.
*   **Pydantic Logfire Integration:** Seamlessly integrates with Pydantic Logfire for real-time debugging, performance monitoring, and behavior tracking.
*    **Multi-agent Applications:** Pydantic AI supports the creations of applications that use multiple agents.

## Components and Examples

### 1. Agents

An `Agent` is the primary interface for interacting with LLMs.  It combines a chosen LLM, a system prompt, optional tools, dependencies, and a result type.

*   **Key Attributes:**
    *   `model`:  The LLM to use (e.g., `'openai:gpt-4o'`, `'google-gla:gemini-1.5-flash'`).
    *   `system_prompt`:  Instructions for the LLM's behavior. Can be static or dynamic.
    *   `result_type`:  A Pydantic model defining the expected output structure.
    *   `dependencies`: Defines the dependency injection.
    * `tools`: function tools that can be used by the agent.

*   **Methods:**
    *   `run_sync(user_query: str, ...)`:  Runs the agent synchronously.
    *   `run(user_query: str, ...)`:  Runs the agent asynchronously.
    *   `run_stream(user_query: str, ...)`: Runs the agent and streams the output.
    * `@agent.system_prompt`: Decorator to define a dynamic system prompt.
      ```python
      @agent.system_prompt
      def dynamic_prompt(ctx):
        return "Be a helpful assistant that always does " + str(ctx.tool_usage)
      ```
    * `@agent.tool`: Decorator to register a function tool.

*   **Example (Basic):**

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class SimpleResult(BaseModel):
    response: str

agent = Agent(
    'openai:gpt-4o',
    system_prompt='Be concise, reply with one sentence.',
    result_type=SimpleResult  # Optional, but recommended for structured output
)

result = agent.run_sync('Where does "hello world" come from?')
print(result.data.response)
# Expected: Output related to the origin of "hello world".```

### 2. Models

Pydantic AI is model-agnostic.  You specify the model when creating an `Agent`.

*   **Supported Providers (Built-in):**
    *   OpenAI
    *   Anthropic
    *   Gemini (via Generative Language API and Vertex AI)
    *   Ollama
    *   Groq
    *   Mistral
    *   Cohere
    *   Bedrock

* **Configuration:**  Each model provider requires configuration (e.g., API keys), typically through environment variables.

*   **Example (Model Specification):**

```python
# Using OpenAI
agent = Agent('openai:gpt-4o')  # Requires OPENAI_API_KEY environment variable

# Using Gemini via Vertex AI
agent = Agent('google-v:gemini-pro') # Requires GOOGLE_APPLICATION_CREDENTIALS

#Using Gemini via Generative Language API
agent = Agent('google-gla:gemini-1.5-pro')
```

### 3. Dependencies

Dependency injection provides data and services to agents, system prompts, tools, and result validators. This is useful for testing and providing context.

*   **Defining Dependencies:** Uses Python's dataclasses.

*   **Example:**

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel

@dataclass
class MyDeps:
    api_key: str
    database_url: str

class QueryResult(BaseModel):
    results: list[str]

@Agent.tool
async def database_query(ctx: RunContext, query: str) -> QueryResult:
  # Access dependencies via ctx.deps
  api_key = ctx.deps.api_key
  # ... use api_key and ctx.deps.database_url to query a database ...
  return QueryResult(results=["Result 1", "Result 2"])
  #return ["Result 1", "Result 2"]

agent = Agent(
    'openai:gpt-3.5-turbo',
    system_prompt="Use the database_query tool to answer user questions.",
    dependencies=MyDeps(api_key="YOUR_API_KEY", database_url="YOUR_DB_URL"),
    result_type=QueryResult,
    tools = [database_query]
)

# The agent can now use the database_query tool, which has access to MyDeps.
```

### 4. Function Tools

Function tools allow agents to call external functions. This is crucial for RAG (Retrieval-Augmented Generation) and other tasks requiring external information.

*   **Registering Tools:** Use the @agent.tool decorator.

*   **Schema Extraction:** Pydantic AI automatically extracts function signatures and docstrings (supports Google, NumPy, and Sphinx styles) to create the tool's schema.

*   **Dynamic Tools:** You can dynamically prepare tools based on the context using the prepare argument in the @agent.tool decorator.

*   **Example:**

```python
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
from typing import List

class WeatherInfo(BaseModel):
    location: str
    temperature: float
    conditions: str

@Agent.tool
async def get_weather(ctx: RunContext, location: str) -> WeatherInfo:
    """Gets the current weather for a given location.

    Args:
        location: The location to get the weather for.
    Returns:
        WeatherInfo:  Weather information.
    """
    # ... (Implementation to fetch weather data) ...
    # Example return:
    return WeatherInfo(location=location, temperature=25.5, conditions="Sunny")
class Answer(BaseModel):
   answer: str
   results: List[WeatherInfo]

agent = Agent(
    'openai:gpt-4o',
    system_prompt="Use the get_weather tool to provide weather information.",
    tools=[get_weather],
    result_type = Answer
)
```

### 5. Results

Pydantic AI uses Pydantic models for structured results, ensuring consistent and validated outputs.

*   **Result Type:** Specified using the result_type argument when creating an Agent.

*   **Validation:** The LLM's response is validated against the specified Pydantic model.

*   **Union Types:** If the result_type is a union of Pydantic models, each model is registered as a separate tool to improve model response correctness.

*   **Result Validators:** For validation that is impossible to do with a pydantic validator, you can create a validator function using the @agent.result_validator decorator.

*   **Example:**

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str

agent = Agent(
    'openai:gpt-4o',
    system_prompt="Search for information about Pydantic.",
    result_type=SearchResult  #  The LLM's output MUST conform to this.
)

result = agent.run_sync("What is Pydantic?")
print(result.data.title)
# ... access other fields of SearchResult ...
```

### Accessing Results

```python
result = agent.run_sync("What is Pydantic?")
# Access all messages
print(result.all_messages())
#Access all messages in json
print(result.all_messages_json())
#Access the messages from only the current run
print(result.new_messages())
#Access the messages from only the current run in json
print(result.new_messages_json())
```

### 6. Messages and Chat History

Pydantic AI provides access to messages exchanged during an agent run, enabling multi-turn conversations.

*   **Accessing Messages:** The RunResult and StreamedRunResult objects provide methods like all_messages(), new_messages(), all_messages_json(), and new_messages_json().

*   **Maintaining Context:** Pass previous messages to the message_history parameter of run, run_sync, or run_stream to maintain context. If message_history has a value, then no new system prompt is generated.

*   **Example:**

```python
from pydantic_ai import Agent

agent = Agent('openai:gpt-4o', system_prompt="Be a helpful assistant.")

result1 = agent.run_sync("What's the capital of France?")
print(result1.data)

result2 = agent.run_sync(
    "What's its population?",
    message_history=result1.new_messages()  # Maintain context
)
print(result2.data)
```

*   **Streaming Messages:**
The messages can also be streamed, this is useful for displaying the messages in real time.

```python
async def stream_messages():
    """Streams new line delimited JSON `Message`s to the client."""

    # stream the user prompt so that can be displayed straight away
    yield MessageTypeAdapter.dump_json(UserPrompt(content=prompt)) + b'\n'

    # get the chat history so far to pass as context to the agent
    messages = list(database.get_messages())

    # run the agent with the user prompt and the chat history
    async with agent.run_stream(prompt, message_history=messages) as result:
```

### 7. Multi-Agent Applications

Pydantic AI supports several approaches to multi-agent applications:

*   **Single Agent Workflows:** The most common case, covered in most of the documentation.

*   **Agent Delegation:** Agents using other agents via tools.

*   **Programmatic Agent Handoff:** Application code calls different agents in succession. One agent finishes a task, then based on the result and other conditions, the code decides to run a different, specific agent.

*   **Graph-Based Control Flow:** For complex cases, a graph-based state machine (using pydantic-graph) controls the execution of multiple agents.

*   **Example (Programmatic Agent Handoff):**

```python
from pydantic_ai import Agent
from pydantic import BaseModel
#Assume Agent and BaseModel definitions for flight_search_agent, and seat_preference_agent
#...
class Flight(BaseModel):
  flight_number: str
  destination: str
  origin: str
  departure_time: str
  arrival_time: str

class Seat(BaseModel):
  seat_number: str
  class_type: str

flight_search_agent = Agent('openai:gpt-4o', system_prompt="Find flights based on user requests.", result_type=Flight)
seat_preference_agent = Agent('openai:gpt-4o', system_prompt="Determine the user's seat preference.", result_type=Seat)
user_query = "Find a flight from London to New York, and I prefer a window seat."

flight_result = flight_search_agent.run_sync(user_query)

if flight_result and flight_result.data:  # Check for a successful result.
  # We have flight information.  Now get the seat preference.
  seat_result = seat_preference_agent.run_sync(user_query)
    if seat_result and seat_result.data:
        print(f"Flight found: {flight_result.data}, Seat preference: {seat_result.data}")
    else:
      print("Could not determine seat preference.")
else:
  print("Could not find a flight.")
```

*   **Example (Agent Delegation):**

```python
from pydantic_ai import Agent, RunContext, tool
from pydantic import BaseModel

# --- Joke Selection Agent ---
class JokeSelectionResult(BaseModel):
    category: str

class JokeSelectionDeps:
    pass
@tool
def joke_factory(ctx: RunContext, category:str) -> str:
  return category

joke_selection_agent = Agent(
    "openai:gpt-3.5-turbo",
    result_type=JokeSelectionResult,
    system_prompt="You are in charge of selecting the category of joke. Be creative. ",
    dependencies=JokeSelectionDeps,
    tools=[joke_factory]
)

# --- Joke Generation Agent ---

```python
class JokeGenerationDeps:
   pass

class JokeGenerationResult(BaseModel):
    joke: str

@tool
async def get_jokes(ctx: RunContext, user_prompt: str) -> list[str]:
    return ["joke 1", "joke 2"]

joke_generation_agent = Agent(
    "openai:gpt-3.5-turbo",
    result_type=JokeGenerationResult,
    system_prompt="You are a joke teller, and you should tell a joke from this category: {ctx.tools.joke_factory}.",
    dependencies=JokeGenerationDeps,
    tools=[get_jokes],
)
```

# --- Combined Workflow ---
```python
# The joke selection agent will be called first
selection_result = joke_selection_agent.run_sync("Tell me a joke")
# Then the category is passed as a parameter ctx.tools.joke_factory
if selection_result.data:
    generation_result = joke_generation_agent.run_sync(
        "Tell me a joke", 
        tools_args={"joke_factory": {"category": selection_result.data.category}}
    )
    print(generation_result.data)
```



