import json
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

app = FastAPI()

# Where the agent runtime keeps its config, cron jobs, and per-agent session logs.
RUNTIME_DIR = Path(os.environ.get("AGENT_RUNTIME_DIR", str(Path.home() / ".agent-runtime"))).expanduser()
CRON_FILE = RUNTIME_DIR / "cron" / "jobs.json"
CONFIG_FILE = RUNTIME_DIR / "agent-runtime.json"

# The agent gateway process this dashboard monitors (systemd user unit + port).
GATEWAY_UNIT = os.environ.get("AGENT_GATEWAY_UNIT", "agent-gateway")
GATEWAY_PORT = int(os.environ.get("AGENT_GATEWAY_PORT", "18789"))

# Pricing table (USD per 1M tokens): (input, output[, cached-input]).
# These are example models; edit this map to match whatever your runtime uses.
# Cost is estimated from this map when a session log does not report a cost directly.
MODEL_PRICING = {
    # OpenAI (defaults)
    "gpt-4o":                    (2.50, 10.00),
    "gpt-4o-mini":               (0.15, 0.60),
    "text-embedding-3-small":    (0.02, 0.00),
    # other providers (example rates; add whatever your runtime uses)
    "glm-5.2":                   (1.40, 4.40, 0.26),
    "glm-4.5-air":               (0.13, 0.85),
    "deepseek-v3":               (0.14, 0.28, 0.0028),
}
# Models covered by a flat-rate plan (no per-token cost): report 0. Add model ids here.
SUBSCRIPTION_MODELS = set()

USD_TO_GBP = 0.79   # approximate; set to 1.0 to display USD

def usd_to_gbp(usd: float) -> float:
    return usd * USD_TO_GBP


def get_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def get_cron_jobs():
    try:
        with open(CRON_FILE) as f:
            data = json.load(f)
            return data.get("jobs", [])
    except Exception:
        return []


def get_system_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    uptime_seconds = (datetime.now(timezone.utc) - boot_time).total_seconds()
    uptime_hours = int(uptime_seconds // 3600)
    uptime_days = uptime_hours // 24
    uptime_str = (
        f"{uptime_days}d {uptime_hours % 24}h" if uptime_days > 0
        else f"{uptime_hours}h {int((uptime_seconds % 3600) // 60)}m"
    )
    return {
        "cpu": round(cpu, 1),
        "ram_used": round(mem.used / 1024**3, 1),
        "ram_total": round(mem.total / 1024**3, 1),
        "ram_pct": mem.percent,
        "disk_used": round(disk.used / 1024**3, 1),
        "disk_total": round(disk.total / 1024**3, 1),
        "disk_pct": round(disk.percent, 1),
        "uptime": uptime_str,
    }


def get_gateway_status():
    """Gateway runs as a user-level systemd service.
    Fallback: check if anything is listening on the gateway port."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", GATEWAY_UNIT],
            capture_output=True, text=True, timeout=3,
        )
        if result.stdout.strip() == "active":
            return True
    except Exception:
        pass
    # Fallback: port check (works regardless of which systemd level owns it).
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr.port == GATEWAY_PORT:
                return True
    except Exception:
        pass
    return False


def _fmt_duration(s: int) -> str:
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def get_gateway_uptime():
    """Returns {up, since_secs, restarts, since_str}.

    Primary: find the pid listening on the gateway port and read its
    process create_time. Restart count: best-effort from `systemctl --user
    show`; falls back to 0 when the user systemd socket is unreachable."""
    info = {"up": False, "since_secs": 0, "restarts": 0, "since_str": "-"}

    # Primary: port -> pid -> create_time
    pid = None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr.port == GATEWAY_PORT and conn.pid:
                pid = conn.pid
                break
    except Exception:
        pass

    if pid:
        try:
            proc = psutil.Process(pid)
            started = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
            delta = int((datetime.now(timezone.utc) - started).total_seconds())
            info["up"] = True
            info["since_secs"] = max(delta, 0)
            info["since_str"] = _fmt_duration(info["since_secs"])
        except Exception:
            pass

    # Best-effort restart count from the user systemd instance.
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", GATEWAY_UNIT, "--property=NRestarts"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("NRestarts="):
                info["restarts"] = int(line.split("=", 1)[1] or 0)
    except Exception:
        pass

    return info


def get_recent_logs(n=30):
    try:
        result = subprocess.run(
            ["journalctl", f"--user-unit={GATEWAY_UNIT}", "-n", str(n),
             "--no-pager", "--output=short-iso"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
        parsed = []
        for line in lines:
            if not line or line.startswith("--"):
                continue
            parts = line.split(" ", 3)
            if len(parts) >= 4:
                ts = parts[0]
                msg = parts[3] if len(parts) > 3 else ""
                level = (
                    "error" if any(w in msg.lower() for w in ["error", "fail", "crash", "fatal"])
                    else "warn" if any(w in msg.lower() for w in ["warn", "retry", "timeout"])
                    else "info"
                )
                parsed.append({"ts": ts[:19].replace("T", " "), "msg": msg[:120], "level": level})
        return list(reversed(parsed))
    except Exception:
        return []


def get_agents():
    cfg = get_config()
    agents_list = cfg.get("agents", {}).get("list", [])
    bindings = cfg.get("bindings", [])
    channels = cfg.get("channels", {})
    gateway_up = get_gateway_status()

    agents = []
    for agent in agents_list:
        aid = agent.get("id")
        channel = None
        for b in bindings:
            if b.get("agentId") == aid:
                channel = b.get("match", {}).get("channel")

        ch_enabled = channels.get(channel, {}).get("enabled", False) if channel else False
        online = gateway_up and (channel is None or ch_enabled)

        raw_name = agent.get("name", aid)
        display_name = raw_name if raw_name != aid else aid.upper()

        raw_model = agent.get("model", "")
        model_str = raw_model.get("primary", "") if isinstance(raw_model, dict) else raw_model

        agents.append({
            "id": aid,
            "name": display_name,
            "model": model_str,
            "channel": channel,
            "online": online,
            "is_sub": False,
        })
    return agents


def _estimate_cost_gbp(model: str, input_tokens: int, output_tokens: int,
                       cache_read_tokens: int, reported_usd: float) -> float:
    """Use reported cost if non-zero, else estimate from the pricing table.
    Subscription-covered models return 0 (flat-rate, no per-token cost).
    Cached-read tokens are billed at the model's cached rate when defined,
    else at the standard input rate."""
    if model in SUBSCRIPTION_MODELS:
        return 0.0
    if reported_usd and reported_usd > 0:
        return usd_to_gbp(reported_usd)
    pricing = MODEL_PRICING.get(model)
    if pricing:
        in_price, out_price = pricing[0], pricing[1]
        cache_price = pricing[2] if len(pricing) > 2 else in_price
        usd = (input_tokens * in_price
               + cache_read_tokens * cache_price
               + output_tokens * out_price) / 1_000_000
        return usd_to_gbp(usd)
    return 0.0


def get_usage_stats():
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=7)
    days_14 = today - timedelta(days=13)

    stats = {
        "total_tokens": 0, "total_cost_gbp": 0.0,
        "today_tokens": 0, "today_cost_gbp": 0.0,
        "week_tokens": 0, "week_cost_gbp": 0.0,
        "by_model": defaultdict(lambda: {"tokens": 0, "cost_gbp": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0}),
        "daily": defaultdict(float),   # date_str -> GBP spend
        "sessions_today": 0, "sessions_week": 0, "sessions_total": 0,
        "last_model": "", "last_active": "", "messages": 0,
    }

    # Scan sessions for every agent listed in the current config.
    cfg = get_config()
    agent_ids = [a.get("id") for a in cfg.get("agents", {}).get("list", []) if a.get("id")]
    dirs = [RUNTIME_DIR / "agents" / aid / "sessions" for aid in agent_ids]

    for d in dirs:
        if not d.exists():
            continue
        for f in d.glob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).date()
                stats["sessions_total"] += 1
                if mtime == today:
                    stats["sessions_today"] += 1
                if mtime >= week_ago:
                    stats["sessions_week"] += 1

                with open(f) as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if obj.get("type") != "message":
                            continue
                        msg = obj.get("message", {})
                        usage = msg.get("usage", {})
                        if not usage:
                            continue

                        # Field names vary by surface: session logs use input/output/
                        # totalTokens + cacheRead; some use inputTokens/outputTokens/total.
                        input_tok = usage.get("input", usage.get("inputTokens", 0))
                        output_tok = usage.get("output", usage.get("outputTokens", 0))
                        cache_read = usage.get("cacheRead", 0)
                        tokens = usage.get("totalTokens",
                                           usage.get("total", input_tok + output_tok + cache_read))
                        cost_obj = usage.get("cost", {})
                        reported_usd = cost_obj.get("total", 0) if isinstance(cost_obj, dict) else 0
                        model = msg.get("model", "unknown")
                        ts_str = obj.get("timestamp", "")

                        cost_gbp = _estimate_cost_gbp(model, input_tok, output_tok, cache_read, reported_usd)

                        try:
                            ts_date = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
                        except Exception:
                            ts_date = None

                        stats["total_tokens"] += tokens
                        stats["total_cost_gbp"] += cost_gbp
                        stats["messages"] += 1
                        stats["by_model"][model]["tokens"] += tokens
                        stats["by_model"][model]["cost_gbp"] += cost_gbp
                        stats["by_model"][model]["calls"] += 1
                        stats["by_model"][model]["input_tokens"] += input_tok
                        stats["by_model"][model]["output_tokens"] += output_tok

                        if model:
                            stats["last_model"] = model
                        if ts_str:
                            stats["last_active"] = ts_str[:19]

                        if ts_date:
                            if ts_date == today:
                                stats["today_tokens"] += tokens
                                stats["today_cost_gbp"] += cost_gbp
                            if ts_date >= week_ago:
                                stats["week_tokens"] += tokens
                                stats["week_cost_gbp"] += cost_gbp
                            if ts_date >= days_14:
                                stats["daily"][str(ts_date)] += cost_gbp
            except Exception:
                pass

    # Fill in zero days for the last 14 days
    daily_filled = {}
    for i in range(14):
        d = str(today - timedelta(days=13 - i))
        daily_filled[d] = round(stats["daily"].get(d, 0.0), 4)

    return {
        "total_tokens": stats["total_tokens"],
        "total_cost_gbp": round(stats["total_cost_gbp"], 2),
        "today_tokens": stats["today_tokens"],
        "today_cost_gbp": round(stats["today_cost_gbp"], 2),
        "week_tokens": stats["week_tokens"],
        "week_cost_gbp": round(stats["week_cost_gbp"], 2),
        "by_model": {k: {
            "tokens": v["tokens"],
            "cost_gbp": round(v["cost_gbp"], 4),
            "calls": v["calls"],
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
        } for k, v in stats["by_model"].items()},
        "daily_spend": daily_filled,
        "sessions_today": stats["sessions_today"],
        "sessions_week": stats["sessions_week"],
        "sessions_total": stats["sessions_total"],
        "last_model": stats["last_model"],
        "last_active": stats["last_active"],
        "messages": stats["messages"],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    with open(Path(__file__).parent / "dashboard_index.html") as f:
        return f.read()


@app.get("/api/usage")
def api_usage():
    return get_usage_stats()


@app.get("/api/status")
def api_status():
    metrics = get_system_metrics()
    agents = get_agents()
    jobs = get_cron_jobs()
    logs = get_recent_logs(25)
    gateway_up = get_gateway_status()
    gateway_uptime = get_gateway_uptime()
    usage = get_usage_stats()

    return {
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "gateway": gateway_up,
        "gateway_uptime": gateway_uptime,
        "metrics": metrics,
        "agents": agents,
        "cron_jobs": jobs,
        "logs": logs,
        "usage": usage,
    }


@app.get("/api/stream")
def stream():
    import time

    def event_generator():
        while True:
            try:
                metrics = get_system_metrics()
                gateway = get_gateway_status()
                gateway_uptime = get_gateway_uptime()
                data = json.dumps({
                    "metrics": metrics,
                    "gateway": gateway,
                    "gateway_uptime": gateway_uptime,
                    "ts": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
                })
                yield f"data: {data}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            time.sleep(10)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7474, log_level="warning")
