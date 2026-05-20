"""Fetch the minimal JAR set the emitted Java needs to compile and run.

mvn is not assumed; we hit Maven Central directly via HTTPS. JARs cache
under `vendor/jars/`. Idempotent — if a JAR is already on disk, we skip
the download. This keeps the pipeline self-contained: clone the repo, run
the conveyor belt, the harness fetches what it needs.

Minimal classpath for CBACT02C (and any non-Spring, OTel-instrumented hex
slice):
  - opentelemetry-api
  - opentelemetry-context   (transitive of api; explicit for clarity)

Adding Spring on top would balloon to ~50 jars; the persona prompt asks
for plain DI in main() instead, so Spring is intentionally absent.
"""
from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JarSpec:
    group: str
    artifact: str
    version: str

    @property
    def filename(self) -> str:
        return f"{self.artifact}-{self.version}.jar"

    def maven_central_url(self) -> str:
        group_path = self.group.replace(".", "/")
        return (
            f"https://repo1.maven.org/maven2/{group_path}/{self.artifact}/"
            f"{self.version}/{self.filename}"
        )


REQUIRED = [
    JarSpec("io.opentelemetry", "opentelemetry-api", "1.40.0"),
    JarSpec("io.opentelemetry", "opentelemetry-context", "1.40.0"),
]


def ensure(vendor_dir: Path, *, specs: list[JarSpec] = REQUIRED) -> list[Path]:
    """Download every spec to `vendor_dir` if not already present. Returns JAR paths."""
    vendor_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for spec in specs:
        target = vendor_dir / spec.filename
        if not target.exists():
            url = spec.maven_central_url()
            print(f"[deps] fetching {spec.filename} from Maven Central")
            urllib.request.urlretrieve(url, target)
        out.append(target)
    return out


def classpath(vendor_dir: Path, extra: list[Path] | None = None) -> str:
    """Build a classpath string from vendor jars + optional extras."""
    jars = list(vendor_dir.glob("*.jar"))
    parts = [str(p) for p in jars]
    for e in extra or []:
        parts.append(str(e))
    return ":".join(parts)
