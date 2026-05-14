"""
config_loader.py — Loads, validates, and saves config.yaml.
Provides module-level CFG singleton (used by run.py).
"""

import logging
import logging.handlers
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

BASE_DIR         = Path(__file__).parent.parent        # project root
DEFAULT_CFG_PATH = BASE_DIR / "config.yaml"


def load_config(path=None) -> dict:
    p = Path(path) if path else DEFAULT_CFG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg: dict, path=None):
    p = Path(path) if path else DEFAULT_CFG_PATH
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_symbols(cfg: dict) -> list:
    source = cfg.get("data_source", "yfinance")
    if source == "alpha_vantage":
        return cfg["universe"].get("symbols_alpha_vantage", [])
    return cfg["universe"].get("symbols_yfinance", [])


def setup_logging(cfg: dict):
    log_cfg  = cfg.get("logging", {})
    level    = getattr(logging, log_cfg.get("level", "INFO"), logging.INFO)
    log_file = BASE_DIR / log_cfg.get("file", "logs/pipeline.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes    = log_cfg.get("max_bytes",    5_242_880),
            backupCount = log_cfg.get("backup_count", 3),
            encoding    = "utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        logger.warning(f"Could not open log file {log_file}: {e}")


# ── Module-level singleton used by run.py ─────────────────────────────────────
try:
    CFG = load_config()
    setup_logging(CFG)
except FileNotFoundError:
    CFG = {}
    logging.basicConfig(level=logging.INFO)
    logger.warning("config.yaml not found — run from project root.")
