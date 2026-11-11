#!/bin/sh
# claudecube: show your Claude usage on a Hatsune Miku CUBEFACE.
#
#   ./claudecube.sh install      set up, send the first picture, then update every 5 minutes
#   ./claudecube.sh now          send a fresh picture right away
#   ./claudecube.sh style C      change the look (A to F, see README)
#   ./claudecube.sh find         forget the saved cube and look for it again
#   ./claudecube.sh log          show what the auto-update has been doing
#   ./claudecube.sh uninstall    stop the auto-update
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
PY="$DIR/.venv/bin/python"
LABEL=com.cubeface.claude-usage
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$DIR/push_face.log"

need_setup() {
  [ -x "$PY" ] || { echo "Run  ./claudecube.sh install  first."; exit 1; }
}

case "$1" in
install)
  [ "$(uname)" = Darwin ] || { echo "Sorry, this only works on macOS."; exit 1; }
  command -v python3 >/dev/null 2>&1 || { echo "python3 is missing. Run  xcode-select --install  and try again."; exit 1; }
  security find-generic-password -s "Claude Code-credentials" >/dev/null 2>&1 || {
    echo "Claude Code is not logged in on this Mac. Run  claude  and then  /login  first."; exit 1; }

  echo "1/3  Installing the Python packages (bleak, Pillow)..."
  [ -x "$PY" ] || python3 -m venv .venv
  "$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade >/dev/null
  # the pip that ships with macOS's Python 3.9 is too old to pick bleak's prebuilt wheels
  "$PY" -m pip install -q --disable-pip-version-check --upgrade pip
  "$PY" -m pip install -q --disable-pip-version-check -r requirements.txt

  echo "2/3  Finding your cube and sending the first picture."
  echo "     If macOS asks to use Bluetooth, click Allow."
  "$PY" push_face.py

  echo "3/3  Turning on the auto-update (every 5 minutes)..."
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/push_face.py</string>
    <string>--if-changed</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
  plutil -lint -s "$PLIST"
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo
  echo "Done. Your cube now shows your Claude usage and refreshes by itself."
  echo "Keep this folder where it is: the auto-update runs from here."
  ;;
now)
  need_setup
  "$PY" push_face.py
  ;;
style)
  need_setup
  case "$2" in
    [A-Fa-f]) echo "$2" | tr a-f A-F > face_style.txt; echo "Style $(cat face_style.txt). Sending it now..."; "$PY" push_face.py ;;
    *) echo "Pick a style letter from A to F, for example:  ./claudecube.sh style C"; exit 1 ;;
  esac
  ;;
find)
  need_setup
  "$PY" push_face.py --find
  ;;
log)
  if [ -f "$LOG" ]; then tail -n 20 "$LOG"; else echo "No log yet."; fi
  ;;
uninstall)
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Auto-update stopped. The cube keeps the last picture until you choose another face in the MikuCube app."
  ;;
*)
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  ;;
esac
