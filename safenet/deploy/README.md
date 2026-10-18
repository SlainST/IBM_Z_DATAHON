# Running SafeNet on IBM LinuxONE

Server: `linux1@148.100.108.149` (s390x, IBM z17, NNPA, 3 vCPU, ~8 GB RAM, Ubuntu 24.04), SSH key only: see
`../LINUXONE_SERVER_GUIDE.md`, and never print, commit or upload `Key.pem`. Everyone shares the `linux1` user:
work in `~/work/<name>`, ask the team before `sudo`, `rm -rf` or `reboot`, and never stop processes you did not
start. Run the scripts with `bash` (copies from Windows lose the executable bit).

## What runs where

```
 your PC                                   LinuxONE (s390x)
 ───────                                   ─────────────────────────────────────────────────────────────
 adapters, demo.py (client/)               ~/IBM_Z_DATAHON           git clone of the repository
   │                                       ~/safenet  ->  ~/IBM_Z_DATAHON/safenet
   └─ tunnel.sh ── SSH :22 ──────────────► uvicorn safenet.api:app × 3 workers   127.0.0.1:8000
      localhost:8000                         systemd user service "safenet-api", its own .venv
                                           PostgreSQL 16 (system service)        127.0.0.1:5432
                                           models/   model1.joblib, model2.joblib, model_info.json
                                           config/api_keys.toml, deploy/linuxone/safenet.env (secrets)
```

The API listens on 127.0.0.1 only; you reach it through an SSH tunnel, so no inbound port has to be open.
Workers keep nothing between requests (points are in Postgres, `../docs/STATE.md`): more workers or more
servers give the same answers.

## Update the running API

```bash
cd ~/IBM_Z_DATAHON && git pull && systemctl --user restart safenet-api
curl -s localhost:8000/health        # "status": "ok", "models": {"model1": "loaded", ...}
```

`git pull` never touches the model files, the keys or `safenet.env` (all gitignored).

## New models

Train on the server, in your own folder (`../models/README.md`), check them, then copy the three files:

```bash
cd ~/work/<name>/safenet                # a copy of the repository, with veri/ from veri_hazirla.py
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -q -r requirements/dev.txt   # once
nice -n 10 .venv/bin/python train.py    # ~20 min on one CPU: models/ and veri/training_report.json
.venv/bin/python -m pytest tests/test_models.py && nice -n 10 .venv/bin/python measure.py
cp models/model1.joblib models/model2.joblib models/model_info.json ~/IBM_Z_DATAHON/safenet/models/
systemctl --user restart safenet-api && curl -s localhost:8000/health   # model_version: the new date
```

A pair trained on a laptop scores garbage here (the hashed features depend on the byte order) and is refused:
`/health` then says `"model1": "fallback"` and the log tells why.

## First time (already done on this server)

```bash
bash deploy/linuxone/check_server.sh                    # arch, z16/z17, NNPA, CPUs, RAM, Python, Postgres, ports
sudo apt install python3-venv python3-numpy python3-scipy python3-sklearn python3-joblib python3-pandas \
     libpq5 postgresql                                  # ask the team first
git clone https://github.com/SlainST/IBM_Z_DATAHON.git ~/IBM_Z_DATAHON && ln -s ~/IBM_Z_DATAHON/safenet ~/safenet
cd ~/safenet && bash deploy/linuxone/setup_server.sh    # .venv (--system-site-packages), requirements, safenet.env
bash deploy/linuxone/setup_postgres.sh                  # role + database, random password into safenet.env
.venv/bin/python scripts/new_api_key.py demo_okul       # one key per platform, printed once
.venv/bin/python scripts/new_api_key.py demo_sosyal
.venv/bin/python scripts/new_api_key.py demo_oyun
mkdir -p ~/.config/systemd/user && cp deploy/linuxone/safenet-api.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now safenet-api
sudo loginctl enable-linger linux1                      # keeps it running after logout and starts it at boot
```

The packages from apt (numpy, scipy, scikit-learn 1.4.1, pandas) are the ones the models are trained with:
pip has no s390x wheels for them, so the venv is created with `--system-site-packages`.
`torch`, `onnxruntime` and `datasets` have no s390x wheels either; nothing here needs them.

Without systemd: `nohup bash deploy/linuxone/run_api.sh > logs/api.log 2>&1 &`.
Logs: `journalctl --user -u safenet-api -f`.

## From your PC

```bash
SAFENET_SSH_KEY=/path/to/Key.pem bash deploy/linuxone/tunnel.sh
#   PowerShell:  ssh -i C:\path\Key.pem -N -L 8000:127.0.0.1:8000 linux1@148.100.108.149
curl http://localhost:8000/health
python demo.py --keys-file /path/to/api_keys.env        # the demo, through the tunnel
```

`/health` reports `arch` (s390x), `machine_type` and `generation` (9175: z17), `nnpa`, the models and when they
were trained, the worker's `pid` (call it a few times: different workers answer) and whether Postgres is
writable. It needs no key.

## Load test

```bash
cat /proc/loadavg                                        # not while a model is training (3 vCPU)
.venv/bin/python bench/load_test.py --key "$KEY" --seconds 30 --concurrency 8 --label "workers=3 pool=5"
psql "$SAFENET_DATABASE_URL" -f bench/cleanup.sql        # takes the bench rows out of the stats
```

Results: `../bench/RESULTS.md`. 3 workers and a pool of 5 measured best on this machine.

## Secrets

- `deploy/linuxone/safenet.env` holds the database password: chmod 600, gitignored.
  `setup_postgres.sh` gives psql the password through stdin, never on a command line.
- `config/api_keys.toml` holds only SHA-256 hashes of the keys. A key is printed once, when it is made, and lives
  in that platform's adapter. Revoke one: delete its line, restart.
- `SAFENET_DEV_KEYS=1` accepts `dev-<platform>` as a key; `run_api.sh` refuses to start with it. Laptops and tests
  only.

## Files

| File | Runs on | Does |
|---|---|---|
| `linuxone/check_server.sh` | server | machine type, NNPA, CPU/RAM, OS, Pythons, Postgres, libpq, libraries, ports; changes nothing |
| `linuxone/setup_server.sh` | server | `.venv` (`--system-site-packages`), `requirements/server.txt`, `models/`, `logs/`, `safenet.env` |
| `linuxone/setup_postgres.sh` | server | role and UTF-8 database, random password, timeouts, `SAFENET_DATABASE_URL` into `safenet.env` |
| `linuxone/run_api.sh` | server | uvicorn with `safenet.env` (shell variables win); refuses dev keys and a CHANGE_ME password |
| `linuxone/load_env.sh` | server | reads `safenet.env` for `run_api.sh` (comments, quotes, Windows line endings) |
| `linuxone/safenet.env.example` | server | every `SAFENET_*` setting, with comments |
| `linuxone/safenet-api.service` | server | the systemd user unit |
| `linuxone/push_to_server.sh` | PC | copies the folder over SSH without venv, models, keys or `safenet.env` (when git is not used) |
| `linuxone/tunnel.sh` | PC | `localhost:8000` → the server's API |
