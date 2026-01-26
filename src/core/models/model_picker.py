from enum import Enum
from typing import Optional, Dict
from pydantic import BaseModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncAzureOpenAI
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider
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
    GOOGLE = "google"
    VERTEX_AI = "vertex_ai"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"

class ModelType(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"

class ModelConfig:
    @staticmethod
    def get_models() -> Dict[ModelType, any]:
        provider = os.getenv('AI_PROVIDER', 'vertex_ai').lower()
        
        if provider == AIProvider.GOOGLE:
            # Simple Google AI Studio with API key
            google_provider = GoogleProvider(api_key=os.getenv('GOOGLE_API_KEY'))
            
            reasoning_model_name = os.getenv('GOOGLE_REASONING_MODEL', 'gemini-2.5-pro')
            coding_model_name = os.getenv('GOOGLE_CODING_MODEL', 'gemini-2.5-pro')
            
            return {
                ModelType.REASONING: GoogleModel(reasoning_model_name, provider=google_provider),
                ModelType.CODING: GoogleModel(coding_model_name, provider=google_provider)
            }
        
        elif provider == AIProvider.VERTEX_AI:
            # Enterprise Vertex AI with service account
            from google.oauth2 import service_account
            
            # Check VERTEX_AI_SERVICE_ACCOUNT_FILE first, then fallback to GOOGLE_APPLICATION_CREDENTIALS
            # Only use if it's a valid file path (not placeholder)
            service_account_file = os.getenv('VERTEX_AI_SERVICE_ACCOUNT_FILE')
            if service_account_file and not os.path.isfile(service_account_file):
                # If set but not a valid file, try fallback
                service_account_file = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            elif not service_account_file:
                # If not set at all, try fallback
                service_account_file = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            
            if not service_account_file:
                raise ValueError("VERTEX_AI_SERVICE_ACCOUNT_FILE or GOOGLE_APPLICATION_CREDENTIALS is required for vertex_ai provider")
            
            credentials = service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            
            vertex_provider = GoogleProvider(
                credentials=credentials,
                vertexai=True,
                project=os.getenv('VERTEX_AI_PROJECT'),
                location=os.getenv('VERTEX_AI_LOCATION', 'global')
            )
            
            reasoning_model_name = os.getenv('VERTEX_AI_REASONING_MODEL', 'gemini-2.5-pro')
            coding_model_name = os.getenv('VERTEX_AI_CODING_MODEL', 'gemini-2.5-pro')
            
            return {
                ModelType.REASONING: GoogleModel(reasoning_model_name, provider=vertex_provider),
                ModelType.CODING: GoogleModel(coding_model_name, provider=vertex_provider)
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
                ModelType.REASONING: OpenAIChatModel(
                    model_name=reasoning_model_name,
                    provider=openai_compat_provider
                ),
                ModelType.CODING: OpenAIChatModel(
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
                ModelType.REASONING: OpenAIResponsesModel(
                    model_name=os.getenv('OPENAI_REASONING_MODEL', 'gpt-4o'),
                    provider=openai_provider
                ),
                ModelType.CODING: OpenAIResponsesModel(
                    model_name=os.getenv('OPENAI_CODING_MODEL', 'gpt-4o'),
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
                ModelType.REASONING: OpenAIResponsesModel(
                    model_name=os.getenv('AZURE_OPENAI_REASONING_MODEL', 'gpt-4o'),
                    provider=azure_provider
                ),
                ModelType.CODING: OpenAIResponsesModel(
                    model_name=os.getenv('AZURE_OPENAI_CODING_MODEL', 'gpt-4o'),
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
            
        elif provider == AIProvider.BEDROCK:
            
            # Create Bedrock provider with AWS credentials
            region_name = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
            aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
            aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
            aws_session_token = os.getenv('AWS_SESSION_TOKEN')
            
            # Create provider with credentials if provided, otherwise use default AWS credential chain
            if aws_access_key_id and aws_secret_access_key and aws_session_token:
                bedrock_provider = BedrockProvider(
                    region_name=region_name,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    aws_session_token=aws_session_token
                )
            elif aws_access_key_id and aws_secret_access_key:
                bedrock_provider = BedrockProvider(
                    region_name=region_name,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key
                )
            else:
                # Use default AWS credential chain (IAM roles, profiles, etc.)
                bedrock_provider = BedrockProvider(region_name=region_name)
            
            reasoning_model_name = os.getenv('BEDROCK_REASONING_MODEL', 'anthropic.claude-3-sonnet-20240229-v1:0')
            coding_model_name = os.getenv('BEDROCK_CODING_MODEL', 'anthropic.claude-3-sonnet-20240229-v1:0')
            
            return {
                ModelType.REASONING: BedrockConverseModel(
                    model_name=reasoning_model_name,
                    provider=bedrock_provider
                ),
                ModelType.CODING: BedrockConverseModel(
                    model_name=coding_model_name,
                    provider=bedrock_provider
                )
            } 

    @staticmethod
    def get_model(model_type: ModelType):
        """Get a specific model by type"""
        return ModelConfig.get_models()[model_type]