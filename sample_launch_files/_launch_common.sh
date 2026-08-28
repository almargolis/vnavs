# Shared launcher logic for the VNAVS node scripts in this directory.
#
# A launch_<node> script sets SESSION and NODE_CMD, then sources this file:
#
#     SESSION=navigator
#     NODE_CMD="python -m vnavsrun.navigator node"
#     source "$(dirname "${BASH_SOURCE[0]}")/_launch_common.sh"
#
# It may also set LAUNCH_DEFAULT=foreground to run in the current terminal
# unless told otherwise (used by the GUI tools -- cvpipeline, mission_control).
# Default is detached.
#
# Usage of the resulting script:
#
#     ./launch_navigator            default mode (detached unless LAUNCH_DEFAULT)
#     ./launch_navigator -f         foreground: run here, Ctrl-C to stop
#     ./launch_navigator -d         detached: screen session "navigator"
#
# Every node reads ./vnavs.ini from its cwd, so this cd's into the launch
# directory (this file's directory) first, then activates the venv
# (VNAVS_VENV, default /home/al/projects/robot/.venv).
#
# Detached mode runs the node inside a shell that STAYS OPEN after the node
# exits, so a crash is still inspectable: `screen -r <name>` shows the
# output/traceback plus a live shell prompt with the node command primed in
# history (up-arrow to re-run it). Use `-f` instead when you just want the
# node in the current terminal with no screen wrapper.
#
#     screen -ls                     list sessions
#     screen -r <SESSION>            attach; Ctrl-A D to detach
#     screen -S <SESSION> -X quit    stop the node / close a kept-open window

set -euo pipefail

: "${SESSION:?_launch_common.sh: caller must set SESSION}"
: "${NODE_CMD:?_launch_common.sh: caller must set NODE_CMD}"

# BASH_SOURCE[1] is the launch_<node> script that sourced us.
_caller="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
_this_script="$(basename "$_caller")"

LAUNCH_DIR="$(cd "$(dirname "$_caller")" && pwd)"
cd "$LAUNCH_DIR"

# Virtualenv holding the -e installed vnavs packages. Override with VNAVS_VENV.
VENV="${VNAVS_VENV:-/home/al/projects/robot/.venv}"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

mode="${LAUNCH_DEFAULT:-detached}"
case "${1:-}" in
    -f | --foreground | fg) mode=foreground ;;
    -d | --detached | bg)   mode=detached ;;
    "") ;;
    *) echo "usage: $_this_script [-f|--foreground | -d|--detached]" >&2; exit 2 ;;
esac

if [ "$mode" = foreground ]; then
    echo "[$SESSION] foreground: $NODE_CMD  (Ctrl-C to stop)"
    # shellcheck disable=SC2086
    exec $NODE_CMD
fi

if screen -ls 2>/dev/null | grep -qE "[.]${SESSION}[[:space:]]"; then
    echo "screen session '$SESSION' already running -- attach with: screen -r $SESSION"
    exit 0
fi

# After the node exits, drop into an interactive shell (with $NODE_CMD primed
# in history) so the output survives a crash and the node can be re-run here.
rc_file="${TMPDIR:-/tmp}/vnavs-keepopen.$SESSION.rc"
{
    echo '[ -f ~/.bashrc ] && source ~/.bashrc'
    printf 'source %q/bin/activate\n' "$VENV"
    printf 'history -s %q\n' "$NODE_CMD"
    printf 'PS1="[%s] \\w\\$ "\n' "$SESSION"
} > "$rc_file"

keep_open="printf '\n[%s] node exited (status %s) -- shell kept open (up-arrow re-runs it; Ctrl-D or \"screen -S %s -X quit\" closes)\n' '$SESSION' \"\$ec\" '$SESSION'; exec bash --rcfile '$rc_file'"

screen -h 20000 -dmS "$SESSION" bash -c "$NODE_CMD; ec=\$?; $keep_open"
echo "started '$SESSION' ($NODE_CMD) in $LAUNCH_DIR"
echo "  attach: screen -r $SESSION      stop: screen -S $SESSION -X quit"
