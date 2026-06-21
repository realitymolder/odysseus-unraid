import json
import os
import subprocess
import time
from pathlib import Path

DATA_DIR = "/data"
STATE_FILE = os.path.join(DATA_DIR, "state.json")
NETWORK_NAME = "odysseus-aio-net"
MANAGED_LABEL = "odysseus.aio.managed=true"

APP_ENV_MAP = {
    "ODYSSEUS_PUID": "PUID",
    "ODYSSEUS_PGID": "PGID",
    "ODYSSEUS_AUTH_ENABLED": "AUTH_ENABLED",
    "ODYSSEUS_ADMIN_USER": "ODYSSEUS_ADMIN_USER",
    "ODYSSEUS_ADMIN_PASSWORD": "ODYSSEUS_ADMIN_PASSWORD",
    "ODYSSEUS_LLM_HOST": "LLM_HOST",
    "ODYSSEUS_LLM_HOSTS": "LLM_HOSTS",
    "ODYSSEUS_OPENAI_API_KEY": "OPENAI_API_KEY",
    "ODYSSEUS_OLLAMA_BASE_URL": "OLLAMA_BASE_URL",
    "ODYSSEUS_HF_TOKEN": "HF_TOKEN",
    "ODYSSEUS_HUGGING_FACE_HUB_TOKEN": "HUGGING_FACE_HUB_TOKEN",
    "ODYSSEUS_DATABASE_URL": "DATABASE_URL",
    "ODYSSEUS_EMBEDDING_URL": "EMBEDDING_URL",
    "ODYSSEUS_EMBEDDING_MODEL": "EMBEDDING_MODEL",
    "ODYSSEUS_EMBEDDING_API_KEY": "EMBEDDING_API_KEY",
    "ODYSSEUS_FASTEMBED_MODEL": "FASTEMBED_MODEL",
    "ODYSSEUS_SECURE_COOKIES": "SECURE_COOKIES",
    "ODYSSEUS_ALLOWED_ORIGINS": "ALLOWED_ORIGINS",
    "ODYSSEUS_CLEANUP_INTERVAL_HOURS": "CLEANUP_INTERVAL_HOURS",
    "ODYSSEUS_DATA_BRAVE_API_KEY": "DATA_BRAVE_API_KEY",
    "ODYSSEUS_GOOGLE_API_KEY": "GOOGLE_API_KEY",
    "ODYSSEUS_GOOGLE_PSE_CX": "GOOGLE_PSE_CX",
    "ODYSSEUS_TAVILY_API_KEY": "TAVILY_API_KEY",
    "ODYSSEUS_SERPER_API_KEY": "SERPER_API_KEY",
    "ODYSSEUS_RESEARCH_LLM_ENDPOINT": "RESEARCH_LLM_ENDPOINT",
    "ODYSSEUS_DISABLE_SMARTRT": "DISABLE_SMARTRT",
    "ODYSSEUS_INPROCESS_POLLERS": "ODYSSEUS_INPROCESS_POLLERS",
    "ODYSSEUS_INPROCESS_TASKS": "ODYSSEUS_INPROCESS_TASKS",
    "ODYSSEUS_SCRIPT_HOST": "ODYSSEUS_SCRIPT_HOST",
    "ODYSSEUS_DISABLE_PRESENCE": "DISABLE_PRESENCE",
}

CONTAINER_SPECS = [
    {
        "name": "odysseus-aio-chromadb",
        "image": "docker.io/chromadb/chroma:latest",
        "binds": {
            "ODYSSEUS_CHROMADB_DATA": ("odysseus_aio_chromadb", "/chroma/chroma"),
        },
        "volumes": {},
        "container_port": lambda e: e.get("ODYSSEUS_CHROMADB_CONTAINER_PORT", "8000"),
        "ports": lambda e: [(e.get("ODYSSEUS_CHROMADB_PORT", "8100"), e.get("ODYSSEUS_CHROMADB_CONTAINER_PORT", "8000"))],
        "env": {"ANONYMIZED_TELEMETRY": "FALSE"},
    },
    {
        "name": "odysseus-aio-searxng",
        "image": "docker.io/searxng/searxng:latest",
        "volumes": {"odysseus_aio_searxng": "/etc/searxng"},
        "container_port": lambda e: e.get("ODYSSEUS_SEARXNG_CONTAINER_PORT", "8080"),
        "ports": lambda e: [(e.get("ODYSSEUS_SEARXNG_PORT", "8080"), e.get("ODYSSEUS_SEARXNG_CONTAINER_PORT", "8080"))],
        "env": lambda e: {
            "SEARXNG_BASE_URL": f"http://localhost:{e.get('ODYSSEUS_SEARXNG_PORT', '8080')}/",
            "SEARXNG_SECRET": e.get("ODYSSEUS_SEARXNG_SECRET", ""),
        },
        "cap_drop": ["ALL"],
        "cap_add": ["CHOWN", "SETGID", "SETUID", "DAC_OVERRIDE"],
    },
    {
        "name": "odysseus-aio-ntfy",
        "image": "docker.io/binwiederhier/ntfy",
        "command": ["serve"],
        "volumes": {"odysseus_aio_ntfy": "/var/cache/ntfy"},
        "container_port": lambda e: e.get("ODYSSEUS_NTFY_CONTAINER_PORT", "80"),
        "ports": lambda e: [(e.get("ODYSSEUS_NTFY_PORT", "8091"), e.get("ODYSSEUS_NTFY_CONTAINER_PORT", "80"))],
        "env": lambda e: {
            "NTFY_BASE_URL": e.get("ODYSSEUS_NTFY_BASE_URL", f"http://localhost:{e.get('ODYSSEUS_NTFY_PORT', '8091')}"),
        },
    },
    {
        "name": "odysseus-aio-app",
        "image": lambda e: e.get("ODYSSEUS_APP_IMAGE", "realitymolder/odysseus:stable"),
        "binds": {
            "ODYSSEUS_APP_DATA": ("odysseus_aio_data", "/app/data"),
            "ODYSSEUS_APP_SSH": ("odysseus_aio_ssh", "/app/.ssh"),
        },
        "volumes": {
            "odysseus_aio_logs": "/app/logs",
            "odysseus_aio_huggingface": "/app/.cache/huggingface",
            "odysseus_aio_local": "/app/.local",
        },
        "container_port": lambda e: e.get("ODYSSEUS_APP_CONTAINER_PORT", "7000"),
        "ports": lambda e: [(e.get("ODYSSEUS_APP_PORT", "7000"), e.get("ODYSSEUS_APP_CONTAINER_PORT", "7000"))],
        "env": lambda e: build_app_env(e),
        "extra_hosts": ["host.docker.internal:host-gateway"],
    },
]


def build_app_env(master_env):
    env = {}
    for master_key, container_key in APP_ENV_MAP.items():
        if master_key in master_env and master_env[master_key]:
            env[container_key] = master_env[master_key]
    searxng_port = master_env.get("ODYSSEUS_SEARXNG_CONTAINER_PORT", "8080")
    chromadb_port = master_env.get("ODYSSEUS_CHROMADB_CONTAINER_PORT", "8000")
    env["SEARXNG_INSTANCE"] = f"http://odysseus-aio-searxng:{searxng_port}"
    env["CHROMADB_HOST"] = "odysseus-aio-chromadb"
    env["CHROMADB_PORT"] = chromadb_port
    return env


def _docker(*args, **kwargs):
    cmd = ["docker"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kwargs)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip(), "output": result.stdout.strip()}
        return {"ok": True, "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out"}
    except FileNotFoundError:
        return {"ok": False, "error": "docker CLI not found"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _docker_json(*args, **kwargs):
    result = _docker(*args, **kwargs)
    if result["ok"] and result["output"]:
        try:
            return {"ok": True, "data": json.loads(result["output"])}
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid JSON from docker"}
    return result


def get_master_env():
    env = {}
    for key in list(APP_ENV_MAP.keys()) + [
        "ODYSSEUS_APP_PORT",
        "ODYSSEUS_APP_CONTAINER_PORT",
        "ODYSSEUS_APP_DATA",
        "ODYSSEUS_APP_SSH",
        "ODYSSEUS_CHROMADB_PORT",
        "ODYSSEUS_CHROMADB_CONTAINER_PORT",
        "ODYSSEUS_CHROMADB_DATA",
        "ODYSSEUS_SEARXNG_PORT",
        "ODYSSEUS_SEARXNG_CONTAINER_PORT",
        "ODYSSEUS_NTFY_PORT",
        "ODYSSEUS_NTFY_CONTAINER_PORT",
        "ODYSSEUS_SEARXNG_SECRET",
        "ODYSSEUS_NTFY_BASE_URL",
        "ODYSSEUS_DNS_SERVERS",
        "ODYSSEUS_NVIDIA_ENABLED",
        "ODYSSEUS_APP_IMAGE",
    ]:
        val = os.environ.get(key, "")
        if val:
            env[key] = val
    return env


def ensure_network():
    r = _docker("network", "inspect", NETWORK_NAME)
    if r["ok"]:
        return True
    r = _docker("network", "create", "--driver", "bridge", NETWORK_NAME)
    return r["ok"]


def ensure_volume(name):
    r = _docker("volume", "inspect", name)
    if r["ok"]:
        return True
    r = _docker("volume", "create", name)
    return r["ok"]


def get_container_status(name):
    r = _docker_json("inspect", name)
    if not r["ok"]:
        return "absent"
    state = r["data"][0]["State"]
    if state["Running"]:
        return "running"
    if state["ExitCode"] != 0:
        return f"exited ({state['ExitCode']})"
    return "stopped"


def resolve_image(spec, master_env):
    image = spec["image"]
    return image(master_env) if callable(image) else image


def get_image_names():
    master_env = get_master_env()
    return {spec["name"]: resolve_image(spec, master_env) for spec in CONTAINER_SPECS}


def pull_image(image):
    return _docker("pull", image)


def create_and_start_container(spec, master_env):
    name = spec["name"]
    image = resolve_image(spec, master_env)
    env = spec["env"] if not callable(spec["env"]) else spec["env"](master_env)
    ports = spec["ports"](master_env) if callable(spec["ports"]) else spec["ports"]

    cmd = ["create", "--name", name, "--network", NETWORK_NAME,
           "--restart", "unless-stopped",
           "--label", MANAGED_LABEL]

    dns_servers = master_env.get("ODYSSEUS_DNS_SERVERS", "8.8.8.8,1.1.1.1")
    for dns in dns_servers.split(","):
        dns = dns.strip()
        if dns:
            cmd.extend(["--dns", dns])

    if name == "odysseus-aio-app" and master_env.get("ODYSSEUS_NVIDIA_ENABLED", "") == "true":
        cmd.extend(["--runtime", "nvidia"])
        cmd.extend(["-e", "NVIDIA_VISIBLE_DEVICES=all"])
        cmd.extend(["-e", "NVIDIA_DRIVER_CAPABILITIES=all"])

    for host_p, container_p in ports:
        host_p_str = str(host_p)
        container_p_str = str(container_p)
        cmd.extend(["-p", f"{host_p_str}:{container_p_str}"])

    binds = spec.get("binds", {})
    for env_var, (fallback_vol, target_path) in binds.items():
        host_path = master_env.get(env_var, "")
        if host_path:
            cmd.extend(["-v", f"{host_path}:{target_path}"])
        else:
            cmd.extend(["-v", f"{fallback_vol}:{target_path}"])

    volumes = spec.get("volumes", {})
    for vol_name, mount_path in volumes.items():
        cmd.extend(["-v", f"{vol_name}:{mount_path}"])

    for key, val in env.items():
        if val:
            cmd.extend(["-e", f"{key}={val}"])

    cap_drop = spec.get("cap_drop", [])
    for cap in cap_drop:
        cmd.extend(["--cap-drop", cap])

    cap_add = spec.get("cap_add", [])
    for cap in cap_add:
        cmd.extend(["--cap-add", cap])

    extra_hosts = spec.get("extra_hosts", [])
    for host in extra_hosts:
        cmd.extend(["--add-host", host])

    command = spec.get("command")
    if command:
        cmd.append(image)
        cmd.extend(command)
    else:
        cmd.append(image)

    r = _docker(*cmd)
    if not r["ok"]:
        return r

    return _docker("start", name)


def remove_container(name):
    r = _docker("rm", "-f", name)
    return r["ok"]


def get_all_statuses():
    names = [s["name"] for s in CONTAINER_SPECS]
    statuses = {}
    for name in names:
        statuses[name] = get_container_status(name)
    return statuses


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_provisioned():
    state = load_state()
    return bool(state.get("containers"))


def deploy_all(log_callback=None):
    master_env = get_master_env()
    state = load_state()

    def log(msg):
        if log_callback:
            log_callback(msg)

    log("Creating network...")
    if not ensure_network():
        return {"ok": False, "error": "Failed to create network"}

    log("Creating volumes...")
    all_volumes = set()
    for spec in CONTAINER_SPECS:
        for vol_name in spec.get("volumes", {}):
            all_volumes.add(vol_name)
        for env_var, (fallback_vol, target_path) in spec.get("binds", {}).items():
            if not master_env.get(env_var, ""):
                all_volumes.add(fallback_vol)
    for vol_name in all_volumes:
        log(f"  Volume: {vol_name}")
        if not ensure_volume(vol_name):
            return {"ok": False, "error": f"Failed to create volume {vol_name}"}

    for spec in CONTAINER_SPECS:
        name = spec["name"]
        image = resolve_image(spec, master_env)
        log(f"Pulling {image}...")
        r = pull_image(image)
        if not r["ok"]:
            log(f"  WARNING: pull failed: {r['error']}")
            log(f"  Continuing with local image if available...")

        existing = get_container_status(name)
        if existing != "absent":
            log(f"Removing existing container: {name}")
            remove_container(name)

        log(f"Creating {name}...")
        r = create_and_start_container(spec, master_env)
        if not r["ok"]:
            log(f"  ERROR: {r['error']}")
            return {"ok": False, "error": f"Failed to create {name}: {r['error']}"}
        log(f"  Started successfully")

    containers = {s["name"]: "running" for s in CONTAINER_SPECS}
    state["containers"] = containers
    state["network"] = NETWORK_NAME
    save_state(state)
    log("Deployment complete!")
    return {"ok": True}


def stop_all(log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)

    for spec in reversed(CONTAINER_SPECS):
        name = spec["name"]
        status = get_container_status(name)
        if status == "running":
            log(f"Stopping {name}...")
            _docker("stop", "-t", "10", name)
            log(f"  Stopped")
    save_state({"provisioned": True})


def update_all(log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)

    for spec in CONTAINER_SPECS:
        name = spec["name"]
        image = resolve_image(spec, get_master_env())
        log(f"Pulling {image}...")
        r = pull_image(image)
        if not r["ok"]:
            log(f"  ERROR: {r['error']}")
            continue
        log(f"  Pulled latest")

        status = get_container_status(name)
        if status == "running":
            log(f"Recreating {name}...")
            remove_container(name)
            r = create_and_start_container(spec, get_master_env())
            if r["ok"]:
                log(f"  Restarted")
            else:
                log(f"  ERROR: {r['error']}")

    log("Update complete!")


def remove_all_containers(log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)

    for spec in reversed(CONTAINER_SPECS):
        name = spec["name"]
        status = get_container_status(name)
        if status != "absent":
            log(f"Removing {name}...")
            _docker("rm", "-f", name)
            log(f"  Removed")

    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    log("All containers removed.")
