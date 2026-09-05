from strands.models import CacheConfig, CacheToolsConfig
from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(
        model_id="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        max_tokens=4096,
        temperature=0.3,
        cache_config=CacheConfig(strategy="auto", ttl="1h"),
        cache_tools=CacheToolsConfig(type="default", ttl="1h"),
    )
