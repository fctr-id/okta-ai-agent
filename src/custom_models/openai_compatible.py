from pydantic_ai.models.openai import OpenAIModel, ModelMessage, ModelSettings
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai import NOT_GIVEN
from itertools import chain
from typing import List, Union
from openai._streaming import AsyncStream
from src.utils.logging import logger
class openAICompatibleModel(OpenAIModel):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        logger.debug("Initializing openAI compatible model")
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
        )
        self.tools = None  # Prevents parallel_tool_calls from being set to True

        # Override the create method to remove 'parallel_tool_calls'
        original_create = self.client.chat.completions.create

        async def custom_create(*args, **kwargs):
            if 'parallel_tool_calls' in kwargs:
                #print("Removing 'parallel_tool_calls' from kwargs")
                kwargs.pop('parallel_tool_calls')
            return await original_create(*args, **kwargs)

        self.client.chat.completions.create = custom_create

    async def _completions_create(
        self, 
        messages: List[ModelMessage], 
        stream: bool, 
        model_settings: ModelSettings | None
    ) -> Union[ChatCompletion, AsyncStream[ChatCompletionChunk]]:
        #print("_completions_create in CustomOpenAIModel called")
        openai_messages = list(chain(*(self._map_message(m) for m in messages)))
        model_settings = model_settings or {}
        model_settings.pop('parallel_tool_calls', None)  # Remove the unsupported field

        # Debug: Print model_settings to verify 'parallel_tool_calls' is removed
        #print("model_settings before API call:", model_settings)

        return await self.client.chat.completions.create(
            model=self.model_name,
            messages=openai_messages,
            stream=stream,
            max_tokens=model_settings.get('max_tokens', NOT_GIVEN),
            temperature=model_settings.get('temperature', NOT_GIVEN),
            top_p=model_settings.get('top_p', NOT_GIVEN),
            timeout=model_settings.get('timeout', NOT_GIVEN),
        )
    
    async def request(self, messages, model_settings=None):
        print("Fireworks CustomOpenAIModel.request called")
        if model_settings:
            model_settings.pop('parallel_tool_calls', None)
            # Debug: Print model_settings after removal
            #print("model_settings after removal:", model_settings)
        return await super().request(messages, model_settings)