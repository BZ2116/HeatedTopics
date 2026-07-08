from src.search_discovery.api_config import api_source_configs


def search_engine_name(source_id: str) -> str:
    config = api_source_configs().get(source_id)
    if config is None:
        return source_id
    return config.display_name
