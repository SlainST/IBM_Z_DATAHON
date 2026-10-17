# Connecting to the LinuxONE Server

- Host: `148.100.108.149`
- User: `linux1`
- Auth: SSH key only (`Key.pem`). The key holder supplies the key; never print, commit, or upload it.

## Connect

```bash
ssh -i <path-to-Key.pem> linux1@148.100.108.149
```

Run a single command without opening a shell:

```bash
ssh -i <path-to-Key.pem> linux1@148.100.108.149 "uname -m"
```

On Serhat's laptop the key path is `C:\Users\Serhat_Tufan\Downloads\Key.pem`.

## If you are a cloud Claude session

Cloud sessions can't reach port 22. Send the command to the Claude Code session on
Serhat's laptop; it runs the command over SSH and returns the output. Otherwise, ask your
human to run it and paste the output back.

## Quick check that the connection works

```bash
ssh -i <path-to-Key.pem> linux1@148.100.108.149 "uname -m; whoami"
```

Expected: `s390x` and `linux1`.
