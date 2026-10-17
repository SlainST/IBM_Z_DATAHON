# Sourced by run_api.sh: reads deploy/linuxone/safenet.env into the environment.
# Handles comments, blank lines, quotes and Windows line endings. Variables already set in the
# shell win, so `SAFENET_WORKERS=1 bash run_api.sh` overrides the file.
load_env() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"; key="${key//[[:space:]]/}"
    val="${line#*=}"; val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
    case "$val" in \"*\") val="${val:1:-1}" ;; \'*\') val="${val:1:-1}" ;; esac
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [ -n "${!key+x}" ] || export "$key=$val"
  done < "$file"
}
