#!/usr/bin/env bash

# Exit on any error
set -e

# Function to show usage
usage() {
    echo "Usage: $0 --folder <path> --modname <module_name> --main <main_function_name>"
    exit 1
}

MAIN="main"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --modname)
            MODNAME="$2"
            shift 2
            ;;
        --folder)
            FOLDER="$2"
            shift 2
            ;;
        --main)
        MAIN="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Check that all files are provided
if [ -z "$MODNAME" ] || [ -z "$FOLDER" ]; then
    echo "Error: Missing required parameters."
    usage
fi

H_FILE="$FOLDER/$MODNAME.h"
C_FILE="$FOLDER/$MODNAME.c"
ISPEC_FILE="$FOLDER/$MODNAME.is"

# Verify that files exist
for f in "$C_FILE" "$H_FILE" "$ISPEC_FILE"; do
    if [ ! -f "$f" ]; then
        echo "Error: File not found - $f"
        exit 1
    fi
done

# Example: Print the file names
echo "Code file:   $C_FILE"
echo "Header file: $H_FILE"
echo "ISpec file:  $ISPEC_FILE"

# ------------------------------------------------------
# Add your actual processing logic here
# For example: compile, analyze, or combine the files
# ------------------------------------------------------

# Example placeholder
echo "Processing files..."
# gcc -o output "$C_FILE"   # Example compile command

echo ""
echo "###########################################"
echo "Checking rule R1 (only callable functions called)"
frama-c -vernfr -nfr-check-calls -nfr-ispec "$ISPEC_FILE" -main "$MAIN" "$C_FILE"
echo "###########################################"

echo ""
echo "###########################################"
echo "Checking rule R2 (no function pointers)"
frama-c -vernfr -nfr-fun-ptrs -nfr-ispec "$ISPEC_FILE" -main "$MAIN" "$C_FILE"
echo "###########################################"

echo ""
echo "###########################################"
echo "Checking rule R3 (no function defs in h-file)"
frama-c -vernfr -nfr-no-fun-defs -keep-unused-types -nfr-ispec "$ISPEC_FILE" -main "$MAIN" "$H_FILE"
echo "###########################################"

echo ""
echo "###########################################"
echo "Checking rule R4 (only include h-files)"
matches=$(grep -nE '#\s*include\s*["<][^">]+\.c[">]' "$C_FILE" || true)

if [[ -n "$matches" ]]; then
    echo "Warning: Found .c files including other .c files: $matches"
fi
echo "###########################################"

echo ""
echo "###########################################"
echo "Checking rule R5 check that all entry-points are declared and defined"
frama-c -vernfr -nfr-all-entries-declared -keep-unused-functions "all" -nfr-ispec "$ISPEC_FILE" -main "$MAIN" "$H_FILE"
frama-c -vernfr -nfr-all-entries-defined -keep-unused-functions "all" -nfr-ispec "$ISPEC_FILE" -main "$MAIN" "$C_FILE"
echo "###########################################"

echo ""
echo "###########################################"
echo "Checking rule R6 check that only entry-points are declared as non-static"
frama-c -vernfr -nfr-only-entries -keep-unused-functions "all" -nfr-ispec "$ISPEC_FILE" -main "$MAIN" "$C_FILE"
echo "###########################################"


echo "Done!"
