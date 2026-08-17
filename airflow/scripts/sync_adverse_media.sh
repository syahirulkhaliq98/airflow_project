#!/usr/bin/env bash
#
# sync_adverse_media.sh
#
# Interactively copies scraper output .xlsx files from the airflow output
# folder to the "Adverse Media Data Upload" OneDrive folder, prompting for
# an end date and one or more sources instead of hardcoding every cp line.
#
# Handles the two filename date formats seen in the output folder:
#   "03 August 2026_05 August 2026_Source.xlsx"   (most sources)
#   "2026-08-03_2026-08-05_Source.xlsx"            (e.g. The Straits Times)

set -uo pipefail

SRC_BASE="/home/khaliq/airflow_project/airflow/output"
DEST="/mnt/c/Users/Syahirul/OneDrive - Verity Intelligence Sdn Bhd/Documents/Adverse media/Adverse Media Data Upload"

if [ ! -d "$SRC_BASE" ]; then
    echo "Source base folder not found: $SRC_BASE"
    exit 1
fi

if [ ! -d "$DEST" ]; then
    echo "Destination folder not found: $DEST"
    echo "(If OneDrive isn't mounted/synced yet, start it and re-run.)"
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Pick end date
# ---------------------------------------------------------------------------
read -rp "End date   (YYYY-MM-DD): " END_IN

# Validate + build the two filename-date formats we need to match against
if ! END_ALT=$(date -d "$END_IN" "+%d %B %Y" 2>/dev/null); then
    echo "Could not parse end date '$END_IN'. Use YYYY-MM-DD."
    exit 1
fi
END_ISO=$(date -d "$END_IN" "+%Y-%m-%d")

echo
echo "Looking for files dated: $END_ALT"
echo "                    (or: $END_ISO)"
echo

# ---------------------------------------------------------------------------
# 2. Pick source(s)
# ---------------------------------------------------------------------------
mapfile -t SOURCES < <(find "$SRC_BASE" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)

if [ ${#SOURCES[@]} -eq 0 ]; then
    echo "No source folders found under $SRC_BASE"
    exit 1
fi

echo "Available sources:"
for i in "${!SOURCES[@]}"; do
    printf "  %2d) %s\n" "$((i+1))" "${SOURCES[$i]}"
done
echo "   a) All sources"
echo

read -rp "Select source number(s), comma-separated, or 'a' for all: " CHOICE

SELECTED=()
if [[ "$CHOICE" == "a" || "$CHOICE" == "A" ]]; then
    SELECTED=("${SOURCES[@]}")
else
    IFS=',' read -ra NUMS <<< "$CHOICE"
    for n in "${NUMS[@]}"; do
        n=$(echo "$n" | xargs)  # trim whitespace
        if [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "${#SOURCES[@]}" ]; then
            SELECTED+=("${SOURCES[$((n-1))]}")
        else
            echo "Skipping invalid selection: $n"
        fi
    done
fi

if [ ${#SELECTED[@]} -eq 0 ]; then
    echo "No valid sources selected. Exiting."
    exit 1
fi

echo
echo "Selected sources: ${SELECTED[*]}"
echo

# ---------------------------------------------------------------------------
# 3. Copy matching files, falling back to manual pick if no auto-match
# ---------------------------------------------------------------------------
COPIED=0
for src in "${SELECTED[@]}"; do
    src_dir="$SRC_BASE/$src"

    mapfile -t MATCHES < <(find "$src_dir" -maxdepth 1 -type f -iname "*.xlsx" \( -iname "*${END_ALT}*" -o -iname "*${END_ISO}*" \))

    if [ ${#MATCHES[@]} -eq 0 ]; then
        echo "[$src] No file matched that end date automatically."
        mapfile -t ALL_FILES < <(find "$src_dir" -maxdepth 1 -type f -iname "*.xlsx" | sort)
        if [ ${#ALL_FILES[@]} -eq 0 ]; then
            echo "[$src] No .xlsx files found at all — skipping."
            continue
        fi
        echo "[$src] Files available in this folder:"
        for i in "${!ALL_FILES[@]}"; do
            printf "    %2d) %s\n" "$((i+1))" "$(basename "${ALL_FILES[$i]}")"
        done
        read -rp "[$src] Pick a number to copy, or press Enter to skip: " pick
        if [[ "$pick" =~ ^[0-9]+$ ]] && [ "$pick" -ge 1 ] && [ "$pick" -le "${#ALL_FILES[@]}" ]; then
            MATCHES=("${ALL_FILES[$((pick-1))]}")
        else
            echo "[$src] Skipped."
            continue
        fi
    fi

    for f in "${MATCHES[@]}"; do
        cp "$f" "$DEST"
        echo "[$src] Copied: $(basename "$f")"
        COPIED=$((COPIED+1))
    done
done

echo
echo "Done. $COPIED file(s) copied to:"
echo "  $DEST"