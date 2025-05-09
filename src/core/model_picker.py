from enum import Enum
from typing import Optional, Dict
from pydantic import BaseModel
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.google_vertex import GoogleVertexProvider  
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncAzureOpenAI
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.gemini import GeminiModelSettings
from pydantic_ai import Agent
import os, json
import httpx
from dotenv import load_dotenv

load_dotenv()

def parse_headers() -> Dict[str, str]:
    """Parse the CUSTOM_HTTP_HEADERS environment variable into a dictionary."""
    headers_str = os.getenv('CUSTOM_HTTP_HEADERS')
    if not headers_str:
        return {}
        
    try:
        # Parse the JSON string into a Python dictionary
        return json.loads(headers_str)
    except json.JSONDecodeError as e:
        print(f"Error parsing CUSTOM_HTTP_HEADERS: {e}")
        return {}

class AIProvider(str, Enum):
    VERTEX_AI = "vertex_ai"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"

class ModelType(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"

class ModelConfig:
    @staticmethod
    def get_models() -> Dict[ModelType, any]:
        provider = os.getenv('AI_PROVIDER', 'vertex_ai').lower()
        
        if provider == AIProvider.VERTEX_AI:
            service_account = os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or os.getenv('VERTEX_AI_SERVICE_ACCOUNT_FILE')
            project_id = os.getenv('VERTEX_AI_PROJECT')
            region = os.getenv('VERTEX_AI_LOCATION', 'us-central1')
            
            reasoning_model_name = os.getenv('VERTEX_AI_REASONING_MODEL', 'gemini-1.5-pro')
            coding_model_name = os.getenv('VERTEX_AI_CODING_MODEL', 'gemini-1.5-pro')
            
            vertex_provider = GoogleVertexProvider(
                service_account_file=service_account,
                project_id=project_id,
                region=region
            )
            
            return {
                ModelType.REASONING: GeminiModel(
                    reasoning_model_name,
                    provider=vertex_provider
                    
                ),
                ModelType.CODING: GeminiModel(
                    coding_model_name,
                    provider=vertex_provider
                )
            }
        
        elif provider == AIProvider.OPENAI_COMPATIBLE:
            custom_headers = parse_headers()
            client = httpx.AsyncClient(verify=False, headers=custom_headers)            
            openai_compat_provider = OpenAIProvider(
                base_url=os.getenv('OPENAI_COMPATIBLE_BASE_URL'),
                api_key=os.getenv('OPENAI_COMPATIBLE_TOKEN'),
                http_client=client
            )
            
            reasoning_model_name = os.getenv('OPENAI_COMPATIBLE_REASONING_MODEL')
            coding_model_name = os.getenv('OPENAI_COMPATIBLE_CODING_MODEL', reasoning_model_name)
            
            return {
                ModelType.REASONING: OpenAIModel(
                    model_name=reasoning_model_name,
                    provider=openai_compat_provider
                ),
                ModelType.CODING: OpenAIModel(
                    model_name=coding_model_name,
                    provider=openai_compat_provider
                )
            }
            
            
        elif provider == AIProvider.OPENAI:
            # Create OpenAI provider
            openai_provider = OpenAIProvider(
                api_key=os.getenv('OPENAI_API_KEY')
            )
            
            return {
                ModelType.REASONING: OpenAIModel(
                    model_name=os.getenv('OPENAI_REASONING_MODEL', 'gpt-4'),
                    provider=openai_provider
                ),
                ModelType.CODING: OpenAIModel(
                    model_name=os.getenv('OPENAI_CODING_MODEL', 'gpt-4-turbo'),
                    provider=openai_provider
                )
            }
            
        elif provider == AIProvider.AZURE_OPENAI:
            # Create Azure OpenAI client
            azure_client = AsyncAzureOpenAI(
                azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
                api_version=os.getenv('AZURE_OPENAI_VERSION', '2024-07-01-preview'),
                api_key=os.getenv('AZURE_OPENAI_KEY')
            )
            
            # Create OpenAI provider with the Azure client
            azure_provider = OpenAIProvider(openai_client=azure_client)
            
            return {
                ModelType.REASONING: OpenAIModel(
                    model_name=os.getenv('AZURE_OPENAI_REASONING_DEPLOYMENT', 'gpt-4'),
                    provider=azure_provider
                ),
                ModelType.CODING: OpenAIModel(
                    model_name=os.getenv('AZURE_OPENAI_CODING_DEPLOYMENT', 'gpt-4'),
                    provider=azure_provider
                )
            }
            
        elif provider == AIProvider.ANTHROPIC:
            # Create Anthropic provider 
            anthropic_provider = AnthropicProvider(
                api_key=os.getenv('ANTHROPIC_API_KEY')
            )
            
            return {
                ModelType.REASONING: AnthropicModel(
                    model_name=os.getenv('ANTHROPIC_REASONING_MODEL', 'claude-3-5-sonnet-latest'),
                    model_settings={
                         'extra_body' :{
                             "thinking" :{
                                 "type": "enabled",
                             }
                         }
                    },
                    provider=anthropic_provider
                ),
                ModelType.CODING: AnthropicModel(
                    model_name=os.getenv('ANTHROPIC_CODING_MODEL', 'claude-3-5-sonnet-latest'),
                    provider=anthropic_provider
                )
            } 

    @staticmethod
    def get_model(model_type: ModelType):
        """Get a specific model by type"""
        return ModelConfig.get_models()[model_type]