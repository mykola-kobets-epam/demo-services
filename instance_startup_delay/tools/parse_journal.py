#!/usr/bin/env python3
"""Parse Aos journal traces (piped on stdin) and report startup timings.

Two kinds of traces are understood:

1. systemd target / unit bring-up (the "aos.target" chain), e.g.:
     Jun 24 15:53:11.309900 main systemd[1]: Starting AOS Service Manager...
     Jun 24 15:53:11.987827 main systemd[1]: Reached target Aos services.

2. Aos-managed service instances, e.g.:
     Jun 24 15:53:11.878048 main aos_sm_app[1618]: (launcher) Start instance: \
         instance={component:1:...:0}, version=6.0.0, runtimeID=..., manifestDigest=...
     Jun 24 15:53:12.019224 main aos_sm_app[1652]: Instance started with ident: \
        {service:0:...:0} instance id: <uuid> time: Jun 24 15:53:12.019163

For every instance the launcher "Start instance" line is correlated with the
instance's own "Instance started with ident" line (matched by the {ident} string)
to compute the startup delay.

Usage:
    journalctl -b -o short-precise | python3 parse_journal.py [--format table|json|csv]

Follow mode also works; press Ctrl+C to stop reading and print the report:
    journalctl -f -o short-precise | python3 parse_journal.py
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

from prettytable import PrettyTable

# Journald short-precise timestamp, e.g. "Jun 24 15:53:11.309900" (no year).
TS = r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d+"
TS_FMT = "%b %d %H:%M:%S.%f"

LINE_RE = re.compile(
    rf"^(?P<ts>{TS})\s+(?P<host>\S+)\s+(?P<proc>[^\[\s]+)(?:\[(?P<pid>\d+)\])?:\s+(?P<msg>.*)$"
)

STARTING_RE = re.compile(r"^Starting (?P<unit>.+?)\.\.\.\s*$")
STARTED_RE = re.compile(r"^Started (?P<unit>.+?)\.\s*$")
REACHED_RE = re.compile(r"^Reached target (?P<target>.+?)\.\s*$")

LAUNCHER_RE = re.compile(
    r"^\(launcher\) Start instance: instance=\{(?P<ident>[^}]*)\}"
    r"(?:, version=(?P<version>[^,]*))?"
    r"(?:, runtimeID=(?P<runtime>[^,]*))?"
)
INSTANCE_RE = re.compile(
    rf"^Instance started with ident: \{{(?P<ident>[^}}]*)\}}"
    rf"(?:\s+instance id:\s*(?P<instid>\S+))?"
    rf"(?:\s+time:\s*(?P<apptime>{TS}))?\s*$"
)

# Which unit/target names belong to the AOS bring-up timeline. The three AOS
# daemons use upper-case "AOS"; the systemd target is "Aos services". This keeps
# generic systemd units (and "Aos base nftables ...") out of the report.
DEFAULT_FILTER = r"AOS|Aos services"


def parse_ts(text, year):
    return datetime.strptime(text, TS_FMT).replace(year=year)


@dataclass
class Instance:
    ident: str
    launcher_ts: datetime = None
    launcher_pid: str = None
    version: str = None
    runtime: str = None
    run_ts: datetime = None      # journald timestamp of the instance's own log
    app_ts: datetime = None      # timestamp the instance itself printed
    instance_id: str = None      # AOS_INSTANCE_ID printed by the instance
    run_pid: str = None
    launcher_line: str = None    # raw journal line of the launcher trace
    run_line: str = None         # raw journal line of the instance self-trace

    @property
    def kind(self):
        return self.ident.split(":", 1)[0] if self.ident else ""

    @property
    def index(self):
        parts = self.ident.split(":")
        return parts[-1] if parts else ""

    @property
    def startup_delay(self):
        if self.launcher_ts and self.run_ts:
            return (self.run_ts - self.launcher_ts).total_seconds()
        return None

    @property
    def log_latency(self):
        # How long after the app printed its line did journald record it.
        if self.run_ts and self.app_ts:
            return (self.run_ts - self.app_ts).total_seconds()
        return None


@dataclass
class Parsed:
    units: list = field(default_factory=list)       # (ts, "Starting"/"Started", name, raw_line)
    targets: list = field(default_factory=list)      # (ts, name, raw_line)
    instances: dict = field(default_factory=dict)    # ident -> Instance
    first_ts: datetime = None


def parse(stream, year, emit=None, rx=None, include_components=False):
    """Parse the journal stream into a `Parsed` snapshot.

    If `emit` is given it is called as emit(ts, event, name, raw_line) for every
    qualifying timeline event the moment it is read, so callers can stream the
    timeline live (rather than buffering it to the end). `rx` selects which
    systemd unit/target names qualify; `include_components` controls whether
    'component' instance traces are emitted.
    """
    out = Parsed()

    def order(ts):
        if out.first_ts is None or ts < out.first_ts:
            out.first_ts = ts

    # When fed from `journalctl -f`, the stream never ends; Ctrl+C should stop
    # reading and fall through to printing the report instead of aborting.
    try:
        _parse_lines(stream, year, out, order, emit, rx, include_components)
    except KeyboardInterrupt:
        pass
    return out


def _emittable_instance(emit, include_components, ident):
    if emit is None:
        return False
    kind = ident.split(":", 1)[0] if ident else ""
    return include_components or kind != "component"


def _parse_lines(stream, year, out, order, emit=None, rx=None, include_components=False):
    for raw in stream:
        line = raw.rstrip("\n")
        m = LINE_RE.match(line)
        if not m:
            continue
        ts = parse_ts(m.group("ts"), year)
        order(ts)
        proc = m.group("proc")
        pid = m.group("pid")
        msg = m.group("msg")

        if proc == "systemd":
            sm = STARTING_RE.match(msg)
            if sm:
                out.units.append((ts, "Starting", sm.group("unit"), line))
                if emit and rx and rx.search(sm.group("unit")):
                    emit(ts, "Starting", sm.group("unit"), line)
                continue
            sm = STARTED_RE.match(msg)
            if sm:
                out.units.append((ts, "Started", sm.group("unit"), line))
                if emit and rx and rx.search(sm.group("unit")):
                    emit(ts, "Started", sm.group("unit"), line)
                continue
            rm = REACHED_RE.match(msg)
            if rm:
                out.targets.append((ts, rm.group("target"), line))
                if emit and rx and rx.search(rm.group("target")):
                    emit(ts, "Reached target", rm.group("target"), line)
                continue
            continue

        lm = LAUNCHER_RE.match(msg)
        if lm:
            ident = lm.group("ident")
            inst = out.instances.setdefault(ident, Instance(ident))
            if inst.launcher_ts is None:
                inst.launcher_ts = ts
                inst.launcher_pid = pid
                inst.version = lm.group("version")
                inst.runtime = lm.group("runtime")
                inst.launcher_line = line
                if _emittable_instance(emit, include_components, ident):
                    emit(ts, "launcher", ident, line)
            continue

        im = INSTANCE_RE.match(msg)
        if im:
            ident = im.group("ident")
            inst = out.instances.setdefault(ident, Instance(ident))
            if inst.run_ts is None:
                inst.run_ts = ts
                inst.run_pid = pid
                inst.run_line = line
                inst.instance_id = im.group("instid")
                if im.group("apptime"):
                    inst.app_ts = parse_ts(im.group("apptime"), year)
                if _emittable_instance(emit, include_components, ident):
                    emit(ts, "self", ident, line)
            continue


def fmt_ts(ts):
    return ts.strftime("%H:%M:%S.%f")[:-3] if ts else "-"


def fmt_ms(seconds):
    return f"{seconds * 1000:.3f}" if seconds is not None else "-"


def delay_s(start, end):
    """Seconds between two timestamps, or None if either is missing."""
    if start and end:
        return (end - start).total_seconds()
    return None


def aos_start_ts(parsed, pattern):
    """Timestamp of the first AOS bring-up "Starting ..." trace.

    This is the moment systemd begins the AOS chain (e.g. "Starting AOS
    Identity and Access Manager..."), used as the anchor for the "from AOS
    start" delay. Only "Starting" events whose unit name matches `pattern`
    are considered.
    """
    rx = re.compile(pattern)
    starts = [ts for ts, kind, name, _ in parsed.units if kind == "Starting" and rx.search(name)]
    return min(starts) if starts else None


def report_instances(parsed, include_components=False):
    """Instances for the startup table, ordered by launch time.

    `component` instances (VMs/firmware, not Aos-managed service instances) never
    emit a self-trace, so they are dropped unless explicitly requested.
    """
    insts = sorted(
        parsed.instances.values(),
        key=lambda i: (i.launcher_ts or i.run_ts or parsed.first_ts),
    )
    if not include_components:
        insts = [i for i in insts if i.kind != "component"]
    return insts


def build_timeline(parsed, pattern, include_components=False):
    """Return startup events as sorted (ts, event, name, raw_line).

    Includes the AOS systemd units/target (filtered by `pattern`) plus, for each
    service instance, the launcher "Start instance" trace and the instance's own
    "Instance started with ident" trace. `raw_line` is the original journal line.
    """
    rx = re.compile(pattern)
    items = (
        [(ts, "Starting", n, raw) for ts, k, n, raw in parsed.units if k == "Starting"]
        + [(ts, "Started", n, raw) for ts, k, n, raw in parsed.units if k == "Started"]
        + [(ts, "Reached target", n, raw) for ts, n, raw in parsed.targets]
    )
    items = [it for it in items if rx.search(it[2])]
    for inst in report_instances(parsed, include_components):
        if inst.launcher_ts:
            items.append((inst.launcher_ts, "launcher", inst.ident, inst.launcher_line))
        if inst.run_ts:
            items.append((inst.run_ts, "self", inst.ident, inst.run_line))
    return sorted(items, key=lambda x: x[0])


class TimelinePrinter:
    """Streams timeline traces as they are parsed, with an offset from the first.

    Offsets are measured from the first trace (= +0.000s), so the "Reached
    target Aos services" line shows the total AOS bring-up delay. Output is
    flushed per line so it appears live under `journalctl -f`.
    """

    def __init__(self, stream=sys.stdout):
        self.base = None
        self.count = 0
        self.stream = stream

    def __call__(self, ts, event, name, raw):
        if self.base is None:
            self.base = ts
        off = (ts - self.base).total_seconds()
        print(f" +{off:8.3f}s  {raw}", file=self.stream, flush=True)
        self.count += 1


def timeline_header():
    return "\n".join([
        "=" * 78,
        " Service startup timeline (aos.target + service instances)",
        "=" * 78,
    ])


def render_instance_table(parsed, pattern=DEFAULT_FILTER, include_components=False):
    lines = []
    lines.append("")
    lines.append("=" * 78)
    lines.append(" Service instance startup")
    lines.append("=" * 78)
    aos_ts = aos_start_ts(parsed, pattern)
    if aos_ts:
        lines.append(f" AOS bring-up start (anchor for fromAos): {fmt_ts(aos_ts)}")
        lines.append("")
    insts = report_instances(parsed, include_components)
    if insts:
        # Two delays per instance:
        #   fromAos    = run_ts - AOS bring-up start ("Starting AOS ..." trace)
        #   fromLaunch = run_ts - launcher "Start instance" trace
        table = PrettyTable()
        table.field_names = [
            "kind", "idx", "launch", "run",
            "fromAos(ms)", "fromLaunch(ms)", "logLat(ms)", "ident",
        ]
        table.align = "r"
        table.align["kind"] = "l"
        table.align["ident"] = "l"
        for inst in insts:
            table.add_row([
                inst.kind,
                inst.index,
                fmt_ts(inst.launcher_ts),
                fmt_ts(inst.run_ts),
                fmt_ms(delay_s(aos_ts, inst.run_ts)),
                fmt_ms(inst.startup_delay),
                fmt_ms(inst.log_latency),
                f"{{{inst.ident}}}",
            ])
        lines.append(table.get_string())
    else:
        lines.append(" (no instance traces found)")

    missing_run = [i for i in insts if i.launcher_ts and not i.run_ts]
    if missing_run:
        lines.append(
            f" launched but no self-trace seen: {len(missing_run)} "
            f"(service launched but never logged its start)"
        )
    return "\n".join(lines)


TIMELINE_EVENT_NAMES = {
    "Starting": "Starting",
    "Started": "Started",
    "Reached target": "ReachedTarget",
    "launcher": "StartInstance",
    "self": "StartInstanceWithId",
}


def to_dict(parsed, pattern=DEFAULT_FILTER, include_components=False):
    timeline = build_timeline(parsed, pattern, include_components)
    base = timeline[0][0] if timeline else None
    aos_ts = aos_start_ts(parsed, pattern)
    return {
        "aos_start_time": fmt_ts(aos_ts),
        "timeline": [
            {
                "time": fmt_ts(ts),
                "offset_s": round((ts - base).total_seconds(), 3) if base else None,
                "event": TIMELINE_EVENT_NAMES.get(event, event),
                "name": name,
                "line": raw,
            }
            for ts, event, name, raw in timeline
        ],
        "instances": [
            {
                "ident": i.ident,
                "kind": i.kind,
                "index": i.index,
                "instance_id": i.instance_id,
                "version": i.version,
                "runtimeID": i.runtime,
                "launcher_time": fmt_ts(i.launcher_ts),
                "run_time": fmt_ts(i.run_ts),
                "app_time": fmt_ts(i.app_ts),
                "delay_from_aos_ms": (
                    round(delay_s(aos_ts, i.run_ts) * 1000, 3)
                    if delay_s(aos_ts, i.run_ts) is not None else None
                ),
                "delay_from_launch_ms": (round(i.startup_delay * 1000, 3) if i.startup_delay is not None else None),
                "log_latency_ms": (round(i.log_latency * 1000, 3) if i.log_latency is not None else None),
            }
            for i in report_instances(parsed, include_components)
        ],
    }


def render_csv(parsed, pattern=DEFAULT_FILTER, include_components=False):
    import csv
    import io

    aos_ts = aos_start_ts(parsed, pattern)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["ident", "kind", "index", "instance_id", "version", "runtimeID",
         "launcher_time", "run_time", "app_time",
         "delay_from_aos_ms", "delay_from_launch_ms", "log_latency_ms"]
    )
    for i in report_instances(parsed, include_components):
        w.writerow(
            [i.ident, i.kind, i.index, i.instance_id or "", i.version or "", i.runtime or "",
             fmt_ts(i.launcher_ts), fmt_ts(i.run_ts), fmt_ts(i.app_ts),
             fmt_ms(delay_s(aos_ts, i.run_ts)), fmt_ms(i.startup_delay), fmt_ms(i.log_latency)]
        )
    return buf.getvalue().rstrip("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=["table", "json", "csv"], default="table",
                    help="output format (default: table)")
    ap.add_argument("--year", type=int, default=datetime.now().year,
                    help="year to assume for timestamps (journald omits it)")
    ap.add_argument("--filter", default=DEFAULT_FILTER,
                    help="regex selecting which unit/target names appear in the "
                         f"timeline (default: {DEFAULT_FILTER!r})")
    ap.add_argument("--include-components", action="store_true",
                    help="also list 'component' instances (VMs/firmware) that "
                         "never emit a self-trace (hidden by default)")
    args = ap.parse_args()

    if args.format == "table":
        # Stream the timeline live as traces arrive (works under `journalctl
        # -f`); the instance table is computed and printed once reading stops.
        print(timeline_header(), flush=True)
        printer = TimelinePrinter()
        parsed = parse(sys.stdin, args.year, emit=printer,
                       rx=re.compile(args.filter), include_components=args.include_components)
        if printer.count == 0:
            print(" (no startup traces found)", flush=True)
        print(render_instance_table(parsed, args.filter, args.include_components))
    else:
        parsed = parse(sys.stdin, args.year)
        if args.format == "json":
            print(json.dumps(to_dict(parsed, args.filter, args.include_components), indent=2))
        else:
            print(render_csv(parsed, args.filter, args.include_components))


if __name__ == "__main__":
    main()
