# WarpX Simulation Models

The active WarpX inputs are organized by model:

```text
simulations/
  inputs/
    model_1_hicks_proton/
    model_2_superposition_proton/
    model_3_superposition_proton_electron/
    model_4_poisson_proton_electron/
  outputs/
    model_1_hicks_proton/
    model_2_superposition_proton/
    model_3_superposition_proton_electron/
    model_4_poisson_proton_electron/
  run_model.sh
  make_particle_movie.py
```

Each model folder contains `input.txt` and a small `run.sh` shim that calls the
shared launcher.

## Models

- `model_1_hicks_proton`: proton tracer model with the Hicks effective
  ponderomotive particle field. The proton species is named `ions` in the WarpX
  deck and does not deposit charge.
- `model_2_superposition_proton`: proton tracer model with the analytic
  finite-electrode superposition RF particle field. The proton species is named
  `ions` and does not deposit charge.
- `model_3_superposition_proton_electron`: quasi-neutral proton/electron model
  with the analytic finite-electrode superposition RF particle field plus
  self-consistent electrostatic fields from charge deposition. The timestep is
  fixed at `1.0e-10 s`, so the fastest electron timescales are intentionally not
  resolved. The electrostatic domain uses grounded PEC field boundaries so the
  Poisson solve remains compatible after absorbing particle boundaries leave a
  net charge.
- `model_4_poisson_proton_electron`: quasi-neutral proton/electron model with
  16 conducting embedded-boundary RF electrodes. Electrode fields and plasma
  self-fields are solved together by the electrostatic Poisson solve with the
  same fixed `1.0e-10 s` timestep. It uses grounded PEC outer field boundaries
  so the Poisson solve remains compatible after absorbing particle boundaries
  leave a net charge.

## Running

Activate the WarpX environment first, then run from inside a model folder:

```bash
cd /Users/thibaultclavier/report/simulations/inputs/model_1_hicks_proton
./run.sh
```

The launcher accepts the same movie options and WarpX command-line overrides:

```bash
./run.sh --no-movie
./run.sh --movie-fps 16 --movie-max-frames 200
./run.sh max_step=20 stop_time=2.0e-8 diag1.intervals=1
```

Every launch creates the next numbered output directory:

```text
simulations/outputs/<model_name>/simN/
```

Each `simN` contains `diags`, `warpx_used_inputs`, `warpx.log`, and, when movie
generation is enabled, `particles.mp4`, `particle_movie_frames`,
`escape_summary.csv`, `plots`, and `movie.log`.

## Smoke Tests

Use tiny runs to check syntax and output routing:

```bash
cd /Users/thibaultclavier/report/simulations/inputs/model_1_hicks_proton
./run.sh --no-movie max_step=2 stop_time=2.0e-9 diag1.intervals=1
```

Repeat the same command from the other model folders. A successful run creates
`simulations/outputs/<model_name>/sim1/warpx.log` and
`simulations/outputs/<model_name>/sim1/warpx_used_inputs`.

The previous `simulations/test_sim/outputs` data is left in place as historical
output and is not part of the active model launcher layout.
