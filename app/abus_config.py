"""
Configuration module for loading environment variables.
Supports .env file loading via python-dotenv.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()


def get_env(key: str, default: str = None) -> str:
    """
    Get environment variable value.
    
    Args:
        key: Environment variable name
        default: Default value if not found (None will return None)
    
    Returns:
        Environment variable value or default
    """
    return os.getenv(key, default)


def _has_real_value(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return not (
        lowered.startswith('your_') or
        'your-' in lowered or
        'your_' in lowered or
        lowered in ('changeme', 'change_me')
    )


def get_azure_speech_key() -> str:
    """Get Azure Speech TTS API key from environment."""
    key = get_env('AZURE_SPEECH_KEY')
    if not key:
        raise ValueError(
            "AZURE_SPEECH_KEY environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return key


def get_azure_speech_region() -> str:
    """Get Azure Speech TTS region from environment."""
    region = get_env('AZURE_SPEECH_REGION')
    if not region:
        raise ValueError(
            "AZURE_SPEECH_REGION environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return region


def get_azure_translator_key() -> str:
    """Get Azure Translator API key from environment."""
    key = get_env('AZURE_TRANSLATOR_KEY')
    if not key:
        raise ValueError(
            "AZURE_TRANSLATOR_KEY environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return key


def get_azure_translator_endpoint() -> str:
    """Get Azure Translator endpoint from environment."""
    endpoint = get_env('AZURE_TRANSLATOR_ENDPOINT')
    if not endpoint:
        raise ValueError(
            "AZURE_TRANSLATOR_ENDPOINT environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return endpoint


def get_azure_translator_region() -> str:
    """Get Azure Translator region from environment."""
    region = get_env('AZURE_TRANSLATOR_REGION')
    if not region:
        raise ValueError(
            "AZURE_TRANSLATOR_REGION environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return region


def get_openai_api_key() -> str:
    """Get OpenAI API key from environment."""
    key = get_env('OPENAI_API_KEY')
    if not key or key.startswith('your_'):
        raise ValueError(
            "OPENAI_API_KEY environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return key


def openai_api_available() -> bool:
    """Check if OpenAI API is available via environment variable."""
    key = get_env('OPENAI_API_KEY')
    return bool(key and not key.startswith('your_'))


def get_openai_translate_model() -> str:
    """Get OpenAI text model for translation."""
    return get_env('OPENAI_TRANSLATE_MODEL', 'gpt-5-mini')


def get_openai_tts_model() -> str:
    """Get OpenAI speech generation model."""
    return get_env('OPENAI_TTS_MODEL', 'gpt-4o-mini-tts')


def get_zai_api_key() -> str:
    """Get Z.AI API key from environment."""
    key = get_env('ZAI_API_KEY')
    if not _has_real_value(key):
        raise ValueError(
            "ZAI_API_KEY environment variable is required. "
            "Please set it in your .env file or environment."
        )
    return key


def zai_api_available() -> bool:
    """Check if Z.AI API is available via environment variable."""
    return _has_real_value(get_env('ZAI_API_KEY'))


def azure_translator_available() -> bool:
    """Check if Azure Translator is available via environment variables."""
    return (
        _has_real_value(get_env('AZURE_TRANSLATOR_KEY')) and
        _has_real_value(get_env('AZURE_TRANSLATOR_ENDPOINT'))
    )
