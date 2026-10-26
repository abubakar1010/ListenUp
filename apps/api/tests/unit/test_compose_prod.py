"""The production Compose file keeps the deployment rules (#112; Architecture 11, 12.1;
ADRs 0032 and 0049; Database Design 9.1).

These read the file as data, so they run anywhere; the local rehearsal recorded in
docs/runbooks/deploy.md runs the same file against real containers.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
PROD = yaml.safe_load((REPO / "infra/compose/compose.prod.yml").read_text())
DEV = yaml.safe_load((REPO / "infra/compose/compose.yml").read_text())
SERVICES: dict[str, dict[str, Any]] = PROD["services"]

SECRET_NAME = re.compile(r"(SECRET|PASSWORD|TOKEN|_KEY$|HMAC|DATABASE_URL|HEADERS)")
INTERPOLATED = re.compile(r"^\$\{[A-Z0-9_]+(:?[-?][^}]*)?\}$")


def env(service: str) -> dict[str, str]:
    return dict(SERVICES[service].get("environment", {}))


def test_postgres_storage_and_mail_are_external_services() -> None:
    assert not {"postgres", "storage", "storage-bucket", "mailpit"} & SERVICES.keys()


def test_every_image_is_an_immutable_release_tag_from_the_registry() -> None:
    ours = {name: s for name, s in SERVICES.items() if "listenup-" in s.get("image", "")}
    assert set(ours) >= {"edge", "api", "worker", "worker-media", "backup", "migrate"}
    for name, service in SERVICES.items():
        assert "build" not in service, name
        image = service["image"]
        if name in ours:
            assert re.fullmatch(
                r"\$\{LISTENUP_REGISTRY:\?[^}]+\}/listenup-[a-z-]+:\$\{LISTENUP_IMAGE_TAG:\?[^}]+\}",
                image,
            ), image
        else:
            assert "@sha256:" in image or re.search(r":\d+\.\d+", image), image


def test_only_the_edge_publishes_ports_and_only_http_and_https() -> None:
    published = {name: s["ports"] for name, s in SERVICES.items() if s.get("ports")}
    assert published == {"edge": ["80:80", "443:443", "443:443/udp"]}


def test_migrations_and_the_bucket_check_are_one_off_containers_run_by_the_deploy() -> None:
    for name in ("migrate", "storage-check"):
        assert SERVICES[name]["profiles"] == ["ops"], name
        assert SERVICES[name]["restart"] == "no", name
    assert SERVICES["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert SERVICES["storage-check"]["command"] == ["python", "-m", "listenup.ops.storage_check"]
    # deploy.sh runs migrate before `up`; a dependency would run it a second time.
    for service in SERVICES.values():
        assert "migrate" not in service.get("depends_on", {})


def test_every_secret_comes_from_the_host_environment_never_a_literal() -> None:
    for name, service in SERVICES.items():
        for key, value in service.get("environment", {}).items():
            if SECRET_NAME.search(key):
                assert INTERPOLATED.match(str(value)), f"{name}.{key} = {value!r}"


def test_each_process_logs_in_as_its_own_database_role() -> None:
    assert env("api")["LISTENUP_DATABASE_URL"] == "${LISTENUP_API_DATABASE_URL:?set in .env}"
    assert env("worker")["LISTENUP_DATABASE_URL"] == "${LISTENUP_WORKER_DATABASE_URL:?set in .env}"
    assert (
        env("worker-media")["LISTENUP_DATABASE_URL"]
        == "${LISTENUP_WORKER_DATABASE_URL:?set in .env}"
    )
    assert (
        env("migrate")["LISTENUP_DATABASE_URL"] == "${LISTENUP_MIGRATE_DATABASE_URL:?set in .env}"
    )
    assert (
        env("backup")["LISTENUP_BACKUP_DATABASE_URL"]
        == "${LISTENUP_MIGRATE_DATABASE_URL:?set in .env}"
    )


@pytest.mark.parametrize(
    ("variable", "allowed"),
    [
        ("LISTENUP_MIGRATE_DATABASE_URL", {"migrate", "backup"}),
        ("LISTENUP_ADMIN_REPORT_DATABASE_URL", {"api"}),
        ("LISTENUP_BACKUP_S3_SECRET_KEY", {"backup", "storage-check"}),
        ("LISTENUP_GOOGLE_CLIENT_SECRET", {"api"}),
        ("LISTENUP_SMTP_PASSWORD", {"worker"}),
        ("LISTENUP_AI_GROQ_API_KEY", {"worker"}),
        ("LISTENUP_OTEL_HEADERS", {"api", "worker", "backup"}),
    ],
)
def test_credentials_reach_only_the_services_that_use_them(
    variable: str, allowed: set[str]
) -> None:
    holders = {
        name
        for name, service in SERVICES.items()
        if any(f"${{{variable}" in str(v) for v in service.get("environment", {}).values())
    }
    assert holders == allowed


def test_production_is_the_default_environment() -> None:
    for name, service in SERVICES.items():
        value = service.get("environment", {}).get("LISTENUP_ENVIRONMENT")
        if name == "media-models":
            # A credential-free downloader: it never serves learners or reads their data.
            assert value == "local"
        elif value is not None:
            assert value == "${LISTENUP_ENVIRONMENT:-production}", name


def test_the_api_trusts_forwarded_client_addresses_only_from_the_edge() -> None:
    edge_ip = SERVICES["edge"]["networks"]["edge"]["ipv4_address"]
    command = SERVICES["api"]["command"]
    assert "--proxy-headers" in command
    assert command[command.index("--forwarded-allow-ips") + 1] == edge_ip
    assert "ports" not in SERVICES["api"]


def test_the_edge_reaches_the_api_only_over_the_edge_network() -> None:
    # Both also sit on the egress network; proxying to the service name could pick that
    # network, and the API would then see Caddy's other address and trust no client
    # address at all (found in the rehearsal). An alias on the edge network alone
    # pins the route to the trusted address.
    caddyfile = (REPO / "infra/caddy/Caddyfile").read_text()
    [upstream] = re.findall(r"reverse_proxy (\S+):8000", caddyfile)
    assert upstream in SERVICES["api"]["networks"]["edge"]["aliases"]
    assert upstream not in SERVICES
    other_aliases = [
        alias
        for service in SERVICES.values()
        if isinstance(service.get("networks"), dict)
        for network, config in service["networks"].items()
        if network != "edge"
        for alias in (config or {}).get("aliases", [])
    ]
    assert upstream not in other_aliases


SANDBOX = [
    "user",
    "init",
    "read_only",
    "cap_drop",
    "security_opt",
    "pids_limit",
    "cpus",
    "mem_limit",
    "memswap_limit",
    "tmpfs",
]


def test_the_media_worker_keeps_the_development_sandbox_exactly() -> None:
    prod, dev = SERVICES["worker-media"], DEV["services"]["worker-media"]
    assert {key: prod[key] for key in SANDBOX} == {key: dev[key] for key in SANDBOX}
    for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        assert env("worker-media")[proxy] == ""
    assert env("worker-media")["NO_PROXY"] == "*"
    assert prod["volumes"] == ["ai-models:/models:ro", "clamav-signatures:/signatures:ro"]


def test_the_media_network_reaches_only_the_relay_to_the_database_and_storage() -> None:
    network = PROD["networks"]["media-data"]
    assert network["internal"] is True
    assert network["driver_opts"] == {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"}
    members = {name for name, s in SERVICES.items() if "media-data" in s.get("networks", {})}
    assert members == {"worker-media", "db-relay"}
    assert list(SERVICES["worker-media"]["networks"]) == ["media-data"]

    relay_ip = SERVICES["db-relay"]["networks"]["media-data"]["ipv4_address"]
    assert SERVICES["worker-media"]["extra_hosts"] == [
        f"${{LISTENUP_RELAY_DB_HOST:?set in .env}}:{relay_ip}",
        f"${{LISTENUP_RELAY_S3_HOST:?set in .env}}:{relay_ip}",
    ]


def test_the_relay_forwards_exactly_two_upstreams_without_inspecting_them() -> None:
    config = PROD["configs"]["db-relay"]["content"]
    assert "mode tcp" in config
    servers = re.findall(r"^\s*server \S+ (.+)$", config, re.MULTILINE)
    assert servers == [
        "${LISTENUP_RELAY_DB_HOST:?set in .env}:${LISTENUP_RELAY_DB_PORT:-5432}",
        "${LISTENUP_RELAY_S3_HOST:?set in .env}:${LISTENUP_RELAY_S3_PORT:-443}",
    ]
    relay = SERVICES["db-relay"]
    assert relay["cap_drop"] == ["ALL"]
    assert relay["security_opt"] == ["no-new-privileges:true"]
    # Compose cannot place an inline config in a read-only container (found in the
    # rehearsal); the relay holds no secrets and runs as HAProxy's own user.
    assert "read_only" not in relay
    assert "user" not in relay  # the image's non-root haproxy user


def test_the_relay_resolves_its_upstreams_again_when_their_addresses_change() -> None:
    # A managed database's failover, or a storage endpoint's rotation, changes the
    # address behind the name; resolving once at start would strand the media pool.
    config = PROD["configs"]["db-relay"]["content"]
    assert re.search(r"^resolvers docker$", config, re.MULTILINE)
    assert "nameserver dns 127.0.0.11:53" in config
    assert re.search(r"^\s*default-server init-addr last,libc,none resolvers docker", config, re.M)
    for line in re.findall(r"^\s*server \S+ .+$", config, re.MULTILINE):
        assert "resolvers" not in line or "resolvers docker" in line


def test_the_fixed_network_addresses_can_be_moved_off_a_clashing_host_range() -> None:
    edge_subnet = "${LISTENUP_EDGE_SUBNET:-172.31.250.0/24}"
    media_subnet = "${LISTENUP_MEDIA_SUBNET:-172.31.251.0/24}"
    edge_ip = "${LISTENUP_EDGE_IP:-172.31.250.10}"
    relay_ip = "${LISTENUP_RELAY_IP:-172.31.251.10}"
    assert PROD["networks"]["edge"]["ipam"]["config"] == [{"subnet": edge_subnet}]
    assert PROD["networks"]["media-data"]["ipam"]["config"] == [{"subnet": media_subnet}]
    assert SERVICES["edge"]["networks"]["edge"]["ipv4_address"] == edge_ip
    assert SERVICES["db-relay"]["networks"]["media-data"]["ipv4_address"] == relay_ip
    example = (REPO / "infra/deploy/env.example").read_text()
    for name in ("EDGE_SUBNET", "EDGE_IP", "MEDIA_SUBNET", "RELAY_IP"):
        assert f"# LISTENUP_{name}=" in example, name


def test_every_database_url_verifies_the_server_certificate() -> None:
    # sslmode=require encrypts but trusts any certificate; with the relay in the path
    # only verify-full proves which server answers.
    example = (REPO / "infra/deploy/env.example").read_text()
    urls = re.findall(r"^LISTENUP_\w+_DATABASE_URL=(.+)$", example, re.MULTILINE)
    assert len(urls) == 5
    for url in urls:
        assert "sslmode=verify-full" in url, url
        assert "sslrootcert=" in url, url


def test_the_backup_service_always_runs_in_production() -> None:
    assert "profiles" not in SERVICES["backup"]
    assert env("backup")["LISTENUP_BACKUP_BUCKET"] == "${LISTENUP_BACKUP_BUCKET:?set in .env}"


def test_long_running_services_restart_and_report_health() -> None:
    for name in ("edge", "api", "worker", "worker-media", "db-relay", "backup", "media-signatures"):
        assert SERVICES[name]["restart"] == "unless-stopped", name
    for name in ("edge", "api"):
        assert SERVICES[name]["healthcheck"]["test"], name
