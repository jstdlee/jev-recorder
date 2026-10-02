"""Config: ~/.config/jrec/config.toml (or $JREC_CONFIG). Built-in defaults cover the Sony ICD-TX660."""
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT = """
library = "~/jrec-library"

[[device]]
name = "sony-tx660"
label = "IC RECORDER"
roots = ["REC_FILE"]
ignore = ["MUSIC"]
extensions = ["mp3", "wav"]
filename_time = '(?:^|_)(\\d{6})_(\\d{4})\\.(?:mp3|wav)$'
timezone = "Asia/Singapore"
auto_import = false

# LLM profiles: any OpenAI-compatible endpoint. `jrec summarize --llm NAME` picks one.
[llm]
default = "local"

[llm.profiles.local]
base_url = "http://localhost:8888/v1"
model = "default"
max_tokens = 32768        # thinking models spend many tokens reasoning
chunk_chars = 256000      # long transcripts are summarised in chunks of this many characters
overlap_chars = 8000      # ... each repeating the end of the previous chunk for context
# api_key_env = "MY_KEY"  # read the key from an environment variable

# jev: Julia-1 choice scoring (/v1/systemone), used by `jrec analyze --engine jev|check`
[jev]
url = "http://127.0.0.1:8011"
model = "julia-1"

[analysis]
engine = "rules"          # rules | llm | jev | check (llm extraction, jev checks each claim)
"""


@dataclass
class Device:
    name: str
    label: str
    roots: list
    filename_time: str
    timezone: str
    ignore: list = field(default_factory=list)
    extensions: list = field(default_factory=lambda: ["mp3", "wav", "m4a", "wma", "amr", "aac", "ogg", "opus", "flac"])
    auto_import: bool = False


@dataclass
class Config:
    library: Path
    devices: list
    llm: dict = field(default_factory=dict)
    path: Path | None = None          # the config file this came from (or the default location)
    jev: dict = field(default_factory=lambda: {"url": "http://127.0.0.1:8011", "model": "julia-1"})
    analysis: dict = field(default_factory=lambda: {"engine": "rules"})

    @property
    def llm_override_path(self):
        """LLM settings edited in the app: merged over [llm] from the config file."""
        return (self.path.parent if self.path else Path("~/.config/jrec").expanduser()) / "llm.json"

    def save_section(self, section, values):
        """Save app-edited values for 'jev' or 'analysis' into the override file."""
        p = self.llm_override_path
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            data = {}
        data.setdefault(section, {}).update(values)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1))
        getattr(self, section).update(values)

    def save_llm(self, name, values, default=None):
        p = self.llm_override_path
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            data = {}
        data.setdefault("profiles", {}).setdefault(name, {}).update(values)
        if default:
            data["default"] = default
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1))
        self.llm.setdefault("profiles", {}).setdefault(name, {}).update(values)
        if default:
            self.llm["default"] = default

    def llm_profile(self, name=None):
        profiles = self.llm.get("profiles", {})
        name = name or self.llm.get("default") or next(iter(profiles), None)
        if name not in profiles:
            raise KeyError(f"no LLM profile {name!r}; have {sorted(profiles)}")
        return profiles[name]

    @property
    def db_path(self):
        return self.library / "jrec.sqlite"

    @property
    def archive(self):
        return self.library / "archive"


def load(path=None):
    path = Path(path or os.environ.get("JREC_CONFIG", "~/.config/jrec/config.toml")).expanduser()
    data = tomllib.loads(path.read_text() if path.exists() else DEFAULT)
    devices = [Device(**d) for d in data.get("device", [])] or \
              [Device(**d) for d in tomllib.loads(DEFAULT)["device"]]
    llm = data.get("llm") or tomllib.loads(DEFAULT)["llm"]
    base = tomllib.loads(DEFAULT)
    cfg = Config(Path(data.get("library", "~/jrec-library")).expanduser(), devices, llm, path,
                 {**base["jev"], **data.get("jev", {})}, {**base["analysis"], **data.get("analysis", {})})
    try:  # settings changed in the app win over the file
        over = json.loads(cfg.llm_override_path.read_text())
        for name, vals in over.get("profiles", {}).items():
            cfg.llm.setdefault("profiles", {}).setdefault(name, {}).update(vals)
        if over.get("default"):
            cfg.llm["default"] = over["default"]
        cfg.jev.update(over.get("jev", {}))
        cfg.analysis.update(over.get("analysis", {}))
    except (OSError, ValueError):
        pass
    return cfg
