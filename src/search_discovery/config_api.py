import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.search_discovery.api_config import api_source_configs, get_api_source_config, mask_secret
from src.search_discovery.cli import _build_registry
from src.search_discovery.connectivity import ConnectionTestResult, test_source_connection
from src.search_discovery.env_file import ensure_env_file, read_env_values, upsert_env_values


def run_config_api_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--set", dest="set_source")
    parser.add_argument("--test", dest="test_source")
    parser.add_argument("--wizard", action="store_true")
    args = parser.parse_args(argv)

    root = Path(".")
    env_path = root / ".env"
    example_path = root / ".env.example"
    ensure_env_file(env_path, example_path)

    if args.list:
        return _list_sources(env_path)
    if args.set_source:
        return _set_source(args.set_source, root, env_path)
    if args.test_source:
        result = test_source_after_save(args.test_source, root)
        _print_test_result(result)
        return 0 if result.status == "ok" else 1
    if args.wizard:
        return _wizard(root, env_path)

    parser.print_help()
    return 1


def _list_sources(env_path: Path) -> int:
    values = read_env_values(env_path)
    print("Search API Configuration\n")
    for source_id, config in api_source_configs().items():
        missing = [key for key in config.env_keys if not values.get(key)]
        if missing:
            print(f"[MISS] {source_id:<22} missing: {', '.join(missing)}")
        else:
            masked = ", ".join(f"{key}={mask_secret(values[key])}" for key in config.env_keys)
            print(f"[OK]   {source_id:<22} {masked}")
    return 0


def _set_source(source_id: str, root: Path, env_path: Path) -> int:
    config = get_api_source_config(source_id)
    print(f"Configuring {config.display_name}")
    print(f"Open: {config.signup_url}\n")
    updates = {}
    for key in config.env_keys:
        value = input(f"{key}: ").strip()
        updates[key] = value
    confirmed = input("Save these keys to .env? [y/N] ").strip().lower()
    if confirmed != "y":
        print("Cancelled.")
        return 1
    upsert_env_values(env_path, updates)
    for key in updates:
        print(f"[OK] Saved {key}")
    print(f"[TEST] Testing {source_id} with query: {config.test_query}")
    result = test_source_after_save(source_id, root)
    _print_test_result(result)
    return 0 if result.status == "ok" else 1


def _wizard(root: Path, env_path: Path) -> int:
    values = read_env_values(env_path)
    for source_id, config in api_source_configs().items():
        if all(values.get(key) for key in config.env_keys):
            continue
        code = _set_source(source_id, root, env_path)
        if code != 0:
            return code
        values = read_env_values(env_path)
    return 0


def test_source_after_save(source_id: str, root: Path) -> ConnectionTestResult:
    load_dotenv(root / ".env", override=True)
    config = get_api_source_config(source_id)
    registry = _build_registry()
    return test_source_connection(source_id, registry=registry, query=config.test_query)


def _print_test_result(result: ConnectionTestResult) -> None:
    if result.status == "ok":
        print(f"[OK] {result.message}")
    else:
        print(f"[FAIL] {result.message}")


def main() -> None:
    raise SystemExit(run_config_api_command())


if __name__ == "__main__":
    main()