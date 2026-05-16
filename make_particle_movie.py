#!/usr/bin/env python3
import argparse
import csv
import os
import shutil
import subprocess
from pathlib import Path

local_cache = Path(os.environ.get("XDG_CACHE_HOME", Path.cwd() / ".cache"))
local_cache.mkdir(exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(local_cache))
mpl_config = Path(os.environ.get("MPLCONFIGDIR", Path.cwd() / ".mplconfig"))
mpl_config.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(mpl_config))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from openpmd_viewer import OpenPMDTimeSeries


R0 = 1.0e-3
RE = R0 / 10.0
R_ESCAPE = R0 + RE


def resolve_diag(path):
    candidate = Path(path)
    if candidate.exists():
        return candidate

    particles_candidate = Path(f"{path}_particles")
    if particles_candidate.exists():
        return particles_candidate

    matches = sorted(Path("diags").glob("*particles*")) if Path("diags").exists() else []
    if len(matches) == 1:
        return matches[0]

    raise FileNotFoundError(f"Could not find openPMD particle diagnostic at {path}")


def select_iterations(iterations, max_frames, escape_history=None):
    if max_frames is None or len(iterations) <= max_frames:
        return iterations
    if escape_history is not None:
        event_iterations = np.asarray(
            [
                int(iteration)
                for iteration in iterations
                if escape_history[int(iteration)]["n_newly_escaped"] > 0
            ],
            dtype=int,
        )
        if len(event_iterations) > 0 and len(event_iterations) < max_frames:
            event_set = set(event_iterations.tolist())
            remaining = np.asarray(
                [int(iteration) for iteration in iterations if int(iteration) not in event_set],
                dtype=int,
            )
            remaining_slots = max_frames - len(event_iterations)
            remaining = select_iterations(remaining, remaining_slots)
            return np.asarray(sorted(set(event_iterations.tolist() + remaining.tolist())))

    indices = np.linspace(0, len(iterations) - 1, max_frames, dtype=int)
    return np.asarray(iterations)[indices]


def filter_iterations(iterations, max_iteration, truncate_at_gap):
    filtered = np.asarray(iterations, dtype=int)
    if max_iteration is not None:
        filtered = filtered[filtered <= max_iteration]

    if truncate_at_gap and len(filtered) > 2:
        gaps = np.diff(filtered)
        normal_gaps = gaps[gaps > 0]
        if len(normal_gaps) > 0:
            median_gap = np.median(normal_gaps)
            gap_indices = np.where(gaps > 10 * median_gap)[0]
            if len(gap_indices) > 0:
                last_index = gap_indices[0] + 1
                print(
                    "detected a large iteration gap; using iterations "
                    f"{filtered[0]}..{filtered[last_index - 1]} only"
                )
                filtered = filtered[:last_index]

    if len(filtered) == 0:
        raise ValueError("No diagnostic iterations remain after filtering")
    return filtered


def frame_time(ts, iteration):
    matches = np.where(ts.iterations == iteration)[0]
    if len(matches) == 0 or not hasattr(ts, "t"):
        return None
    return float(ts.t[matches[0]])


def ids_to_set(particle_ids):
    return set(np.asarray(particle_ids, dtype=np.uint64).tolist())


def build_escape_history(ts, iterations, species):
    _, _, initial_ids_array = ts.get_particle(
        ["x", "z", "id"], species=species, iteration=int(iterations[0])
    )
    initial_ids = ids_to_set(initial_ids_array)
    first_iteration = int(iterations[0])
    escaped_ids = set()
    lost_ids = set()
    rows = {}

    for iteration in iterations:
        x, z, ux, uz, particle_ids = ts.get_particle(
            ["x", "z", "ux", "uz", "id"], species=species, iteration=int(iteration)
        )
        particle_ids_array = np.asarray(particle_ids, dtype=np.uint64)
        radius = np.sqrt(x * x + z * z)
        radial_momentum = x * ux + z * uz
        present_ids = ids_to_set(particle_ids_array)
        active_before_escape_ids = initial_ids - escaped_ids - lost_ids
        outward_escape_ids = ids_to_set(
            particle_ids_array[(radius > R_ESCAPE) & (radial_momentum > 0.0)]
        )
        if int(iteration) == first_iteration:
            newly_escaped_ids = set()
        else:
            newly_escaped_ids = outward_escape_ids & active_before_escape_ids

        escaped_ids.update(newly_escaped_ids)
        lost_ids.update(active_before_escape_ids - present_ids)

        active_ids = present_ids & (initial_ids - escaped_ids - lost_ids)
        active_mask = np.asarray([pid in active_ids for pid in particle_ids_array], dtype=bool)
        visible_escaped_mask = np.asarray(
            [pid in escaped_ids for pid in particle_ids_array], dtype=bool
        )

        active_inside = int(np.count_nonzero(active_mask & (radius <= R_ESCAPE)))
        active_outside = int(np.count_nonzero(active_mask & (radius > R_ESCAPE)))
        current_trapped = len(active_ids)
        escaped_total = len(escaped_ids)
        lost_total = len(lost_ids)
        trapped_estimate = len(initial_ids) - escaped_total - lost_total

        rows[int(iteration)] = {
            "iteration": int(iteration),
            "time_s": frame_time(ts, int(iteration)),
            "n_initial": len(initial_ids),
            "n_visible": len(present_ids),
            "n_current_trapped": current_trapped,
            "n_active_visible": len(active_ids),
            "n_active_inside": active_inside,
            "n_active_outside": active_outside,
            "n_newly_escaped": len(newly_escaped_ids),
            "n_visible_after_escape": int(np.count_nonzero(visible_escaped_mask)),
            "n_escaped_circular": escaped_total,
            "n_lost_rectangular": lost_total,
            "n_remaining_trapped": trapped_estimate,
            "active_ids": active_ids,
        }

    return rows


def write_escape_summary(rows, output):
    if output is None:
        return
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "iteration",
        "time_s",
        "n_initial",
        "n_visible",
        "n_current_trapped",
        "n_active_visible",
        "n_active_inside",
        "n_active_outside",
        "n_newly_escaped",
        "n_visible_after_escape",
        "n_escaped_circular",
        "n_lost_rectangular",
        "n_remaining_trapped",
    ]
    with output_path.open("w", newline="") as summary_file:
        writer = csv.DictWriter(summary_file, fieldnames=fieldnames)
        writer.writeheader()
        for iteration in sorted(rows):
            row = {field: rows[iteration][field] for field in fieldnames}
            writer.writerow(row)
    print(f"wrote escape summary to {output_path}")


def sample_trapped_history(rows, n_samples):
    iterations = sorted(rows)
    diagnostic_times = np.asarray(
        [rows[iteration]["time_s"] for iteration in iterations],
        dtype=float,
    )
    diagnostic_counts = np.asarray(
        [rows[iteration]["n_current_trapped"] for iteration in iterations],
        dtype=int,
    )

    if n_samples is None:
        return diagnostic_times, diagnostic_counts
    if n_samples < 2:
        raise ValueError("--history-samples must be at least 2")

    sampled_times = np.linspace(diagnostic_times[0], diagnostic_times[-1], n_samples)
    indices = np.searchsorted(diagnostic_times, sampled_times, side="right") - 1
    indices = np.clip(indices, 0, len(diagnostic_counts) - 1)
    return sampled_times, diagnostic_counts[indices]


def write_trapped_history(rows, plot_dir, output_txt=None, n_samples=1000):
    if plot_dir is None:
        return
    plot_dir = Path(plot_dir)
    plot_dir.mkdir(parents=True, exist_ok=True)
    if output_txt is None:
        output_txt = plot_dir / "trapped_particles.txt"
    else:
        output_txt = Path(output_txt)
        output_txt.parent.mkdir(parents=True, exist_ok=True)

    times, trapped_counts = sample_trapped_history(rows, n_samples)

    with output_txt.open("w") as history_file:
        for time, count in zip(times, trapped_counts):
            history_file.write(f"{time:.18e} {count}\n")

    fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
    ax.step(np.asarray(times) * 1.0e6, trapped_counts, where="post", lw=1.8)
    ax.set_xlabel("time [us]")
    ax.set_ylabel("trapped particles")
    ax.grid(True, alpha=0.25)
    fig.savefig(plot_dir / "trapped_particles.png", dpi=180)
    plt.close(fig)
    print(f"wrote trapped-particle history to {output_txt}")
    print(f"wrote trapped-particle plot to {plot_dir / 'trapped_particles.png'}")


def write_movie(frame_dir, output, fps):
    ffmpeg = shutil.which("ffmpeg")
    output_path = Path(output)
    if ffmpeg is None:
        gif_output = output_path if output_path.suffix.lower() == ".gif" else output_path.with_suffix(".gif")
        write_gif(frame_dir, gif_output, fps)
        print(f"ffmpeg not found; wrote GIF fallback {gif_output}")
        return

    pattern = str(frame_dir / "particles_%06d.png")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            pattern,
            "-pix_fmt",
            "yuv420p",
            output,
        ],
        check=True,
    )


def write_gif(frame_dir, output, fps):
    from PIL import Image

    frame_paths = sorted(frame_dir.glob("particles_*.png"))
    if not frame_paths:
        raise FileNotFoundError(f"No frames found in {frame_dir}")

    frames = [Image.open(path).convert("P", palette=Image.Palette.ADAPTIVE) for path in frame_paths]
    duration_ms = max(1, int(1000 / fps))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    for frame in frames:
        frame.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("diag", nargs="?", default="diags")
    parser.add_argument("--species", default="ions")
    parser.add_argument(
        "--movie-species",
        choices=["ions", "electrons", "both"],
        default=None,
        help="species rendered in movie frames (default: same as --species)",
    )
    parser.add_argument("--ion-color", default="tab:blue")
    parser.add_argument("--electron-color", default="tab:orange")
    parser.add_argument("--no-speed-colormap", action="store_true")
    parser.add_argument("--out", default="particles.mp4")
    parser.add_argument("--frame-dir", default="particle_movie_frames")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--max-iteration", type=int, default=None)
    parser.add_argument("--summary", default="escape_summary.csv")
    parser.add_argument("--plot-dir", default=None)
    parser.add_argument("--trapped-history", default=None)
    parser.add_argument("--history-samples", type=int, default=1000)
    parser.add_argument("--no-truncate-at-gap", action="store_true")
    parser.add_argument("--no-movie", action="store_true")
    args = parser.parse_args()

    diag_path = resolve_diag(args.diag)
    frame_dir = None
    if not args.no_movie:
        frame_dir = Path(args.frame_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        for old_frame in frame_dir.glob("particles_*.png"):
            old_frame.unlink()

    ts = OpenPMDTimeSeries(str(diag_path))
    diagnostic_iterations = filter_iterations(
        ts.iterations,
        args.max_iteration,
        truncate_at_gap=not args.no_truncate_at_gap,
    )
    escape_history = build_escape_history(ts, diagnostic_iterations, args.species)
    write_escape_summary(escape_history, args.summary)
    plot_dir = args.plot_dir
    if plot_dir is None and args.out:
        plot_dir = Path(args.out).parent / "plots"
    write_trapped_history(
        escape_history,
        plot_dir,
        args.trapped_history,
        n_samples=args.history_samples,
    )
    if args.no_movie:
        print("skipping movie generation (--no-movie)")
        return

    movie_species = args.movie_species if args.movie_species is not None else args.species
    movie_histories = {args.species: escape_history}
    if movie_species == "both":
        for species_name in ("ions", "electrons"):
            if species_name not in movie_histories:
                movie_histories[species_name] = build_escape_history(
                    ts, diagnostic_iterations, species_name
                )
    elif movie_species not in movie_histories:
        movie_histories[movie_species] = build_escape_history(
            ts, diagnostic_iterations, movie_species
        )

    iterations = select_iterations(diagnostic_iterations, args.max_frames, escape_history)

    for frame_index, iteration in enumerate(iterations):
        fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True)
        scatter = None

        def render_species(species_name, color=None, label=None):
            nonlocal scatter
            x, z, ux, uz, w, particle_ids = ts.get_particle(
                ["x", "z", "ux", "uz", "w", "id"],
                species=species_name,
                iteration=int(iteration),
            )
            metrics = movie_histories[species_name][int(iteration)]
            particle_ids_array = np.asarray(particle_ids, dtype=np.uint64)
            active_mask = np.asarray(
                [pid in metrics["active_ids"] for pid in particle_ids_array], dtype=bool
            )
            x = x[active_mask]
            z = z[active_mask]
            ux = ux[active_mask]
            uz = uz[active_mask]
            w = w[active_mask]
            trapped_now = int(np.count_nonzero(active_mask))
            escaped_cumulative = metrics["n_escaped_circular"]

            if len(x) == 0:
                return trapped_now, escaped_cumulative

            if args.no_speed_colormap or movie_species == "both":
                ax.scatter(
                    x * 1.0e3,
                    z * 1.0e3,
                    c=color if color is not None else "tab:blue",
                    s=12.0,
                    alpha=0.85,
                    linewidths=0,
                    label=label,
                )
            else:
                speed_gamma_beta = np.sqrt(ux * ux + uz * uz)
                scatter = ax.scatter(
                    x * 1.0e3,
                    z * 1.0e3,
                    c=speed_gamma_beta,
                    s=np.clip(w / np.max(w), 0.2, 1.0) * 12.0,
                    cmap="viridis",
                    alpha=0.85,
                    linewidths=0,
                )

            return trapped_now, escaped_cumulative

        if movie_species == "both":
            ions_trapped, ions_escaped = render_species(
                "ions", color=args.ion_color, label="ions"
            )
            electrons_trapped, electrons_escaped = render_species(
                "electrons", color=args.electron_color, label="electrons"
            )
            title_status = (
                f"trapped ions = {ions_trapped}, electrons = {electrons_trapped}, "
                f"escaped ions = {ions_escaped}, electrons = {electrons_escaped}"
            )
        else:
            trapped_now, escaped_cumulative = render_species(
                movie_species,
                color=args.ion_color if movie_species == "ions" else args.electron_color,
                label=movie_species,
            )
            title_status = (
                f"species = {movie_species}, trapped now = {trapped_now}, "
                f"escaped cumulative = {escaped_cumulative}"
            )

        trap = plt.Circle((0.0, 0.0), R0 * 1.0e3, fill=False, color="black", lw=1.2)
        escape = plt.Circle(
            (0.0, 0.0), R_ESCAPE * 1.0e3, fill=False, color="tab:red", lw=1.0, ls="--"
        )
        ax.add_patch(trap)
        ax.add_patch(escape)

        time_value = frame_time(ts, int(iteration))
        time_label = f", t = {time_value * 1.0e6:.3g} us" if time_value is not None else ""
        ax.set_title(
            f"step {int(iteration)}{time_label}\n"
            f"{title_status}"
        )
        ax.set_xlabel("x [mm]")
        ax.set_ylabel("project y / WarpX z [mm]")
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(-1.2, 1.2)
        ax.set_ylim(-1.2, 1.2)
        ax.grid(True, alpha=0.25)
        if movie_species == "both":
            ax.legend(loc="upper right")
        if scatter is not None:
            cbar = fig.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
            cbar.set_label("gamma beta")

        fig.savefig(frame_dir / f"particles_{frame_index:06d}.png", dpi=160)
        plt.close(fig)

    write_movie(frame_dir, args.out, args.fps)
    print(f"wrote frames to {frame_dir}")


if __name__ == "__main__":
    main()
