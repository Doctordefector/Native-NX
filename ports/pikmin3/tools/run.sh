#!/bin/sh
# boot out/Pikmin3.exe for N seconds (default 60) with the extracted RomFS; log in out/Pikmin3.log
cd "$(dirname "$0")/../out"
SWR_ROMFS="$PWD/../../../work/0100F4C009322000/extract/RomFS" timeout ${1:-60} ./Pikmin3.exe "$@" > run.txt 2>&1
echo "exit $?"
