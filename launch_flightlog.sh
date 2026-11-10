#!/bin/sh
# Opens the flight log page. The first run installs NumPy and Matplotlib.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer was not found."
  echo "Install Python, then run this file again."
  echo "This launcher cannot install Python for you."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating a local environment and installing flightlog."
  echo "This needs an internet connection once, for NumPy and Matplotlib."
  python3 -m venv .venv || {
    echo "Could not create .venv. Install the Python venv module and try again."
    exit 1
  }
  .venv/bin/python -m pip install -e . || {
    echo "Install failed. Check the message above. An internet connection is required the first time."
    exit 1
  }
fi

exec .venv/bin/python -m flightlog ui
