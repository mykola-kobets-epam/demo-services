# instance_startup_delay

Demo service used to test service instance startup delay.

On start it prints the Aos service instance identity (item ID, subject ID,
instance index, instance ID and secret) read from environment variables. Because
it prints the identity immediately on launch, the logged start time can be used
to measure how long it takes for an instance to be started.

Two equivalent implementations of the service are provided:

- `instance-startup-delay-python/src_any/startup-delay-demo-service.py` — Python
  version (architecture-independent).
- `instance-startup-delay-c/` — C version (`src/main.c` + `CMakeLists.txt`),
  built into an architecture-specific binary `startup-delay-demo-service`.

`config.yaml` currently deploys the C version.

Build the C binary (mirrors the `client-server` demo):

- `./build.sh --toolchain=/path/to/environment-setup-core2-64-aos-linux`
- Optional: `--arch=<name>` (default is `x86`)

Build output: `instance-startup-delay-c/<arch>/startup-delay-demo-service`

`tools/parse_journal.py` parses the journal and reports per-instance startup
delays (see `tools/requirements.txt`).
