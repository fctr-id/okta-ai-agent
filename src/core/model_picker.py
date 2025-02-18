from enum import Enum
from typing import Optional, Dict
from pydantic import BaseModel
from pydantic_ai.models.vertexai import VertexAIModel
from src.custom_models.openai_compatible import openAICompatibleModel
from openai import AsyncAzureOpenAI
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai import Agent
import os
from dotenv import load_dotenv

load_dotenv()

class AIProvider(str, Enum):
    VERTEX_AI = "vertex_ai"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    OPENAI_COMPATIBLE = "openai_compatible"

class ModelType(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"

class ModelConfig:
    @staticmethod
    def get_models() -> Dict[ModelType, any]:
        provider = os.getenv('AI_PROVIDER', 'vertex_ai').lower()
        #print(f"Provider: {provider}")
        
        if provider == AIProvider.VERTEX_AI:
            service_account = os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or os.getenv('VERTEX_AI_SERVICE_ACCOUNT_FILE') 
            return {
                ModelType.REASONING: VertexAIModel(
                    os.getenv('VERTEX_AI_REASONING_MODEL'),
                    service_account_file=service_account
                ),
                ModelType.CODING: VertexAIModel(
                    os.getenv('VERTEX_AI_CODING_MODEL'),
                    service_account_file=service_account
                )
            }
        
        elif provider == AIProvider.OPENAI_COMPATIBLE:
            return {
                ModelType.REASONING: openAICompatibleModel(
                    os.getenv('OPENAI_COMPATIBLE_REASONING_MODEL'),
                    base_url=os.getenv('OPENAI_COMPATIBLE_BASE_URL'),
                    api_key=os.getenv('OPENAI_COMPATIBLE_TOKEN')
                ),
                ModelType.CODING: openAICompatibleModel(
                    os.getenv('OPENAI_COMPATIBLE_CODING_MODEL'),
                    base_url=os.getenv('OPENAI_COMPATIBLE_BASE_URL'),
                    api_key=os.getenv('OPENAI_COMPATIBLE_TOKEN')
                )
            }
            
        elif provider == AIProvider.OPENAI:
            return {
                ModelType.REASONING: OpenAIModel(
                    os.getenv('OPENAI_REASONING_MODEL', 'gpt-4'),
                    api_key=os.getenv('OPENAI_API_KEY')
                ),
                ModelType.CODING: OpenAIModel(
                    os.getenv('OPENAI_CODING_MODEL', 'gpt-4-turbo'),
                    api_key=os.getenv('OPENAI_API_KEY')
                )
            }
            
        elif provider == AIProvider.AZURE_OPENAI:
            azure_client = AsyncAzureOpenAI(
                azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
                api_version=os.getenv('AZURE_OPENAI_VERSION', '2024-07-01-preview'),
                api_key=os.getenv('AZURE_OPENAI_KEY')
            )
            return {
                ModelType.REASONING: OpenAIModel(
                    os.getenv('AZURE_OPENAI_REASONING_MODEL', 'gpt-4'),
                    openai_client=azure_client
                ),
                ModelType.CODING: OpenAIModel(
                    os.getenv('AZURE_OPENAI_CODING_MODEL', 'gpt-4-turbo'),
                    openai_client=azure_client
                )
            }

    @staticmethod
    def get_model(model_type: ModelType):
        """Get a specific model by type"""
        return ModelConfig.get_models()[model_type]