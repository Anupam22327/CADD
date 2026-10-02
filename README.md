# CADD Discovery

A Windows-friendly local research workspace. The existing dashboard and live 3Dmol.js viewer are preserved; a FastAPI service now provides SQLite project records, actual RCSB PDB retrieval, structure storage, ligand SMILES validation and calculated RDKit descriptors when RDKit is installed.

## Run on Windows

1. Install Python 3.10 or newer and ensure `python` is on PATH.
2. Run `setup.bat` to create `.venv` and install `backend/requirements.txt`.
3. Run `check_environment.bat` to inspect optional scientific tools.
4. Run `start.bat`. The dashboard opens at `http://127.0.0.1:8080`; API docs are at `http://127.0.0.1:8000/docs`.

Manual API startup: `uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`. Dashboard only: `python -m http.server 8080`.

Run the backend regression checks with `.venv\Scripts\python.exe -m unittest discover -s backend\tests -v` after setup.

API data is stored below `data/` by default. Set `CADD_DATA_DIR` to choose a different writable data directory. The browser reports whether the local API is connected. Structure coordinates are downloaded from RCSB only on request and retained unchanged under `data/structures/`.

## Implemented API

- `GET /api/health` and `GET /api/integrations`: database, Python, Biopython, RDKit, Vina, GROMACS and ADMET configuration states.
- `POST /api/projects`, `GET /api/projects`, `GET /api/projects/{id}`: SQLite project creation and retrieval.
- `POST /api/structures/{pdb_id}`: validates the accession, retrieves and checks real coordinate data from RCSB, stores the original PDB, and records provenance. Optional `project_id` associates it with a project.
- `GET /api/structures/{pdb_id}/file`: serves a previously retrieved PDB.
- `POST /api/ligands/validate`: validates SMILES and returns RDKit calculated descriptors plus a Lipinski assessment; does not claim ADMET predictions.
- `POST /api/ligands/prepare`: reproducibly adds hydrogens, generates an ETKDGv3 conformer and writes SDF. This is not Vina-ready PDBQT; atom types and charges need a compatible documented tool.
- `POST /api/uploads/ligand`: extension, size and empty-file checks for SDF, MOL, MOL2 and PDBQT. Parsing is not claimed.
- `POST /api/docking/configuration`: validates prepared PDBQT file inputs, numeric box parameters, and Vina availability.
- `POST /api/docking/jobs`: queues real AutoDock Vina execution in a FastAPI background task when Vina and prepared PDBQT inputs are available; stores output pose, logs, parsed affinities, errors and status.
- `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/logs`, `GET /api/jobs/{id}/poses` and `GET /api/reports/{project_id}`: job status, logs, successful poses and structured project report data.
- `POST /api/md/jobs`: clearly reports missing GROMACS or the unimplemented preparation workflow; never returns synthetic simulation results.

FastAPI validates request data and reports structured HTTP errors. The OpenAPI UI is generated at `/docs`.

## Scientific status and limitations

The preexisting dashboard includes demonstration disease and target summaries. These remain labeled demo content; there is no live disease-to-target evidence provider or automatic target ranking. The 3D viewer retrieves structures directly from RCSB, and the API can persist a verified PDB response. RCSB records must still be checked for organism, chain, construct and suitability for a research question.

AutoDock Vina can execute only when it is installed and researchers supply properly prepared receptor and ligand PDBQT files plus a binding box. This build does not prepare receptor PDBQT, and RDKit SDF output is not directly Vina-compatible. Protein/ligand interaction analysis, virtual screening, report file export, ADMET prediction and GROMACS simulation are not implemented. Their states must not be interpreted as computed results. GROMACS and Vina are external dependencies and are not installed by `setup.bat`; configure them separately and add their executables to PATH. ADMET remains `ADMET ENGINE NOT CONFIGURED`.

RDKit and Biopython are declared dependencies. If installation is unavailable, the API still starts when FastAPI dependencies are present; RDKit ligand validation returns HTTP 503 rather than fabricated output. Scientific descriptors are calculations, not measured or predicted ADMET values. All computational findings require experimental validation.

## Files

- `index.html`, `css/style.css`, `js/app.js`, `js/visualization.js`: preserved dashboard and molecular viewer.
- `js/backend.js`: local API connection and browser API helpers.
- `backend/app/main.py`: FastAPI routes and SQLite persistence.
- `backend/requirements.txt`: Python dependencies.
- `setup.bat`, `start.bat`, `check_environment.bat`: Windows setup, startup and environment checks.
"# CADD" 
