"""Config: ~/.config/jrec/config.toml (or $JREC_CONFIG). Built-in defaults cover the Sony ICD-TX660."""
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
    return Config(Path(data.get("library", "~/jrec-library")).expanduser(), devices)
