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
import ssl
from dotenv import load_dotenv
from src.utils.logging import logger

load_dotenv()


try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False

def _count_certificates(file_path: str) -> int:
    """Count certificates in a PEM file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            return content.count('-----BEGIN CERTIFICATE-----')
    except Exception as e:
        logger.debug(f"Could not count certificates in {file_path}: {e}")
        return 0

def _find_custom_ca_file(ca_filename: str) -> Optional[str]:
    """Find custom CA file in possible locations."""
    if not ca_filename:
        return None
        
    possible_paths = [
        os.path.join('/app/src/backend/certs', ca_filename),  # Docker path
        os.path.join('src/backend/certs', ca_filename)        # Local path
    ]
    
    for ca_path in possible_paths:
        if os.path.isfile(ca_path):
            logger.debug(f"Found custom CA file at: {ca_path}")
            return ca_path
    
    logger.warning(f"Custom CA file '{ca_filename}' not found in any of: {possible_paths}")
    return None

def get_ca_bundle_path() -> Optional[str]:
    """Get CA bundle path from SSL certs directory or fallback to certifi/system."""
    ca_filename = os.getenv('SSL_CA_BUNDLE_FILENAME')
    
    if ca_filename:
        logger.debug(f"Looking for custom CA bundle: {ca_filename}")
        custom_path = _find_custom_ca_file(ca_filename)
        if custom_path:
            return custom_path
    
    # Fallback to certifi if available
    if CERTIFI_AVAILABLE:
        certifi_path = certifi.where()
        logger.debug(f"Using certifi CA bundle: {certifi_path}")
        return certifi_path
    
    logger.debug("Using system default CA store")
    return None

def create_http_client_with_ssl_config() -> httpx.AsyncClient:
    """Create HTTP client with SSL configuration supporting multiple CA sources."""
    verify_ssl = os.getenv('VERIFY_SSL', 'true').lower() == 'true'
    
    if not verify_ssl:
        logger.warning("SSL verification DISABLED - ignoring all certificate errors")
        return httpx.AsyncClient(verify=False, timeout=httpx.Timeout(60.0))
    
    # Check for custom CA bundle first
    ca_filename = os.getenv('SSL_CA_BUNDLE_FILENAME')
    custom_ca_path = _find_custom_ca_file(ca_filename) if ca_filename else None
    
    if custom_ca_path:
        logger.info(f"Configuring SSL with hybrid approach: system + custom CAs")
        
        # Create SSL context that loads system/certifi CAs first
        context = ssl.create_default_context()
        
        # Log what system CAs we're starting with
        if CERTIFI_AVAILABLE:
            certifi_path = certifi.where()
            system_cert_count = _count_certificates(certifi_path)
            logger.debug(f"Loaded {system_cert_count} system certificates from certifi: {certifi_path}")
        else:
            logger.debug("Loaded system default CA certificates (count unknown)")
        
        # Add custom certificates to the existing context
        try:
            context.load_verify_locations(custom_ca_path)
            custom_cert_count = _count_certificates(custom_ca_path)
            logger.info(f"Added {custom_cert_count} custom certificates from: {custom_ca_path}")
            
            # Summary log
            if CERTIFI_AVAILABLE:
                total_estimated = system_cert_count + custom_cert_count
                logger.info(f"SSL context now contains ~{total_estimated} certificates (system + custom)")
            else:
                logger.info(f"SSL context contains system CAs + {custom_cert_count} custom certificates")
                
        except Exception as e:
            logger.error(f"Failed to load custom CA bundle {custom_ca_path}: {e}")
            logger.info("Falling back to system-only CA certificates")
            # Context still has system CAs, so continue
        
        return httpx.AsyncClient(verify=context, timeout=httpx.Timeout(60.0))
    
    # Standard fallback - system CAs only
    ca_bundle = get_ca_bundle_path()
    if ca_bundle:
        cert_count = _count_certificates(ca_bundle)
        logger.info(f"Using system-only CA bundle with {cert_count} certificates: {ca_bundle}")
        return httpx.AsyncClient(verify=ca_bundle, timeout=httpx.Timeout(60.0))
    
    logger.info("Using system default SSL configuration")
    return httpx.AsyncClient(timeout=httpx.Timeout(60.0))


def parse_headers() -> Dict[str, str]:
    """Parse the CUSTOM_HTTP_HEADERS environment variable into a dictionary."""
    headers_str = os.getenv('CUSTOM_HTTP_HEADERS')
    if not headers_str:
        return {}
        
    try:
        # Parse the JSON string into a Python dictionary
        return json.loads(headers_str)
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing CUSTOM_HTTP_HEADERS: {e}")
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
                    provider=vertex_provider,
                )
            }
        
        elif provider == AIProvider.OPENAI_COMPATIBLE:
            custom_headers = parse_headers()
            client = create_http_client_with_ssl_config()
            if custom_headers:
                # Merge custom headers with existing client headers
                client.headers.update(custom_headers)         
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