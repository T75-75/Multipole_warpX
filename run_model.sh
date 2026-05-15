#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <model_name> [--no-movie] [--movie-fps N] [--movie-max-frames N] [warpx overrides...]" >&2
}

if (($# < 1)); then
    usage
    exit 2
fi

model_name="$1"
shift

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
model_dir="${script_dir}/inputs/${model_name}"
input_file="${model_dir}/input.txt"
movie_script="${script_dir}/make_particle_movie.py"

if [[ ! -d "$model_dir" ]]; then
    echo "Unknown model '${model_name}': ${model_dir} does not exist." >&2
    exit 2
fi

if [[ ! -f "$input_file" ]]; then
    echo "Missing input deck: ${input_file}" >&2
    exit 2
fi

make_movie=1
movie_fps=12
movie_max_frames=120
warpx_args=()

while (($#)); do
    case "$1" in
        --no-movie)
            make_movie=0
            ;;
        --movie-fps)
            shift
            movie_fps="${1:?--movie-fps requires a value}"
            ;;
        --movie-max-frames)
            shift
            movie_max_frames="${1:?--movie-max-frames requires a value}"
            ;;
        --)
            shift
            warpx_args+=("$@")
            break
            ;;
        *)
            warpx_args+=("$1")
            ;;
    esac
    shift
done

if ! command -v warpx.2d >/dev/null 2>&1; then
    echo "warpx.2d was not found. Activate the WarpX environment first." >&2
    exit 127
fi

output_root_abs="${script_dir}/outputs/${model_name}"
output_root_rel="../../outputs/${model_name}"
mkdir -p "$output_root_abs"

run_number=1
while true; do
    run_dir_abs="${output_root_abs}/sim${run_number}"
    if mkdir "$run_dir_abs" 2>/dev/null; then
        break
    fi
    run_number=$((run_number + 1))
done

run_dir_rel="${output_root_rel}/sim${run_number}"
diag_prefix="${run_dir_rel}/diags"
used_inputs="${run_dir_rel}/warpx_used_inputs"
log_file="${run_dir_rel}/warpx.log"
movie_file="${run_dir_rel}/particles.mp4"
movie_frames="${run_dir_rel}/particle_movie_frames"
movie_summary="${run_dir_rel}/escape_summary.csv"
movie_log="${run_dir_rel}/movie.log"

echo "Model: ${model_name}"
echo "Writing this run to ${run_dir_rel}"

cd "$model_dir"

warpx_cmd=(warpx.2d input.txt)
if ((${#warpx_args[@]})); then
    warpx_cmd+=("${warpx_args[@]}")
fi
warpx_cmd+=(
    "diag1.file_prefix=${diag_prefix}"
    "warpx.used_inputs_file=${used_inputs}"
)

"${warpx_cmd[@]}" 2>&1 | tee "$log_file"

if [[ "$make_movie" == 1 ]]; then
    if [[ ! -f "$movie_script" ]]; then
        echo "Missing movie script: ${movie_script}" >&2
        exit 2
    fi

    python_bin="${PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
        if command -v python3 >/dev/null 2>&1; then
            python_bin="python3"
        elif command -v python >/dev/null 2>&1; then
            python_bin="python"
        else
            echo "Neither python3 nor python was found. Disable movies with --no-movie or activate the analysis environment." >&2
            exit 127
        fi
    fi

    export XDG_CACHE_HOME="${run_dir_rel}/.cache"
    export MPLCONFIGDIR="${run_dir_rel}/.mplconfig"

    echo "Creating particle movie at ${movie_file}" | tee "$movie_log"
    "$python_bin" "$movie_script" "$diag_prefix" \
        --out "$movie_file" \
        --frame-dir "$movie_frames" \
        --summary "$movie_summary" \
        --fps "$movie_fps" \
        --max-frames "$movie_max_frames" \
        2>&1 | tee -a "$movie_log"
fi
