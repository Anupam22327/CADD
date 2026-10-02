from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("CADD_DATA_DIR", ROOT / "data")).resolve()
STRUCTURE_DIR = DATA_DIR / "structures"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "cadd.sqlite3"
for directory in (DATA_DIR, STRUCTURE_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CADD Discovery API", version="0.2.0", description="Local research workflow API. Predictions are never fabricated.")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"], allow_methods=["*"], allow_headers=["*"])


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, disease TEXT NOT NULL DEFAULT '', target TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS structures(id INTEGER PRIMARY KEY, project_id TEXT REFERENCES projects(id), pdb_id TEXT NOT NULL, path TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL, retrieved_at TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ligands(id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), name TEXT NOT NULL, input_type TEXT NOT NULL, source TEXT NOT NULL, descriptors TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        """)


@app.on_event("startup")
def startup() -> None:
    init_db()


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    disease: str = Field(default="", max_length=200)
    target: str = Field(default="", max_length=200)


class LigandInput(BaseModel):
    name: str = Field(default="Ligand", max_length=120)
    smiles: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None


class LigandPrepareInput(LigandInput):
    random_seed: int = Field(default=2026, ge=0, le=2_147_483_647)


class DockingConfig(BaseModel):
    protein_path: str
    ligand_path: str
    center_x: float
    center_y: float
    center_z: float
    size_x: float = Field(gt=0, le=100)
    size_y: float = Field(gt=0, le=100)
    size_z: float = Field(gt=0, le=100)
    exhaustiveness: int = Field(default=8, ge=1, le=256)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def binary_status(binary: str) -> dict[str, Any]:
    path = shutil.which(binary)
    return {"status": "AVAILABLE" if path else "DEPENDENCY MISSING", "path": path}


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        init_db()
        database = "AVAILABLE"
    except sqlite3.Error as exc:
        database = f"FAILED: {exc}"
    try:
        import Bio  # noqa: F401
        biopython = "AVAILABLE"
    except ImportError:
        biopython = "DEPENDENCY MISSING"
    try:
        from rdkit import rdBase
        rdkit = {"status": "AVAILABLE", "version": rdBase.rdkitVersion}
    except ImportError:
        rdkit = {"status": "DEPENDENCY MISSING"}
    return {"status": "ok", "database": database, "python": os.sys.version.split()[0], "biopython": biopython,
            "rdkit": rdkit, "vina": binary_status("vina"), "gromacs": binary_status("gmx"), "admet": "ADMET ENGINE NOT CONFIGURED"}


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at DESC")]


@app.post("/api/projects", status_code=201)
def create_project(data: ProjectInput) -> dict[str, Any]:
    record = {"id": str(uuid.uuid4()), **data.model_dump(), "created_at": now()}
    with connect() as db:
        db.execute("INSERT INTO projects VALUES(:id,:name,:disease,:target,:created_at)", record)
    return record


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    with connect() as db:
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        return {**dict(project), "structures": [dict(x) for x in db.execute("SELECT * FROM structures WHERE project_id=?", (project_id,))],
                "ligands": [dict(x) for x in db.execute("SELECT * FROM ligands WHERE project_id=?", (project_id,))],
                "jobs": [dict(x) for x in db.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC", (project_id,))]}


@app.post("/api/structures/{pdb_id}")
def retrieve_structure(pdb_id: str, project_id: str | None = None) -> dict[str, Any]:
    accession = pdb_id.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", accession):
        raise HTTPException(422, "PDB ID must be four alphanumeric characters")
    if project_id:
        with connect() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise HTTPException(404, "Project not found")
    url = f"https://files.rcsb.org/download/{accession}.pdb"
    try:
        request = Request(url, headers={"User-Agent": "CADD-Discovery/0.2 research-client"})
        with urlopen(request, timeout=20) as response:
            raw = response.read(50_000_001)
        if len(raw) > 50_000_000:
            raise HTTPException(413, "Structure file exceeds 50 MB limit")
        text = raw.decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise HTTPException(404 if exc.code == 404 else 502, f"RCSB returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(502, f"RCSB retrieval failed: {exc}") from exc
    if not re.search(r"^(ATOM  |HEADER|TITLE )", text, re.M) or not re.search(r"^(ATOM  |HETATM)", text, re.M):
        raise HTTPException(502, "RCSB response was not a valid coordinate-bearing PDB file")
    title = " ".join(re.findall(r"^TITLE\s+\d*\s*(.*)$", text, re.M)).strip() or "Title unavailable"
    path = STRUCTURE_DIR / f"{accession}.pdb"
    path.write_text(text, encoding="utf-8")
    record = {"pdb_id": accession, "title": title, "source": url, "status": "COMPLETED", "path": str(path), "retrieved_at": now(), "bytes": len(raw)}
    with connect() as db:
        db.execute("INSERT INTO structures(project_id,pdb_id,path,source,title,retrieved_at,status) VALUES(?,?,?,?,?,?,?)",
                   (project_id, accession, str(path), url, title, record["retrieved_at"], "COMPLETED"))
    return record


@app.get("/api/structures/{pdb_id}/file")
def get_structure_file(pdb_id: str) -> FileResponse:
    if not re.fullmatch(r"[A-Za-z0-9]{4}", pdb_id):
        raise HTTPException(422, "Invalid PDB ID")
    path = STRUCTURE_DIR / f"{pdb_id.upper()}.pdb"
    if not path.exists():
        raise HTTPException(404, "Structure has not been retrieved")
    return FileResponse(path, media_type="chemical/x-pdb", filename=path.name)


@app.post("/api/ligands/validate")
def validate_ligand(data: LigandInput) -> dict[str, Any]:
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
    except ImportError:
        raise HTTPException(503, "RDKit is not installed. Install requirements.txt to enable chemical validation.")
    mol = Chem.MolFromSmiles(data.smiles)
    if mol is None:
        raise HTTPException(422, "RDKit could not parse the supplied SMILES")
    canonical = Chem.MolToSmiles(mol, isomericSmiles=True)
    properties = {"molecular_weight": round(Descriptors.MolWt(mol), 3), "logp": round(Descriptors.MolLogP(mol), 3),
                  "h_bond_donors": int(Lipinski.NumHDonors(mol)), "h_bond_acceptors": int(Lipinski.NumHAcceptors(mol)),
                  "rotatable_bonds": int(Lipinski.NumRotatableBonds(mol)), "tpsa": round(rdMolDescriptors.CalcTPSA(mol), 3)}
    violations = sum((properties["molecular_weight"] > 500, properties["logp"] > 5, properties["h_bond_donors"] > 5, properties["h_bond_acceptors"] > 10))
    if data.project_id:
        with connect() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (data.project_id,)).fetchone():
                raise HTTPException(404, "Project not found")
            db.execute("INSERT INTO ligands VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), data.project_id, data.name, "SMILES", "User supplied", json.dumps({**properties,"lipinski_violations": violations}), "VALIDATED", now()))
    return {"status": "COMPLETED", "name": data.name, "source": "User supplied SMILES", "canonical_smiles": canonical,
            "descriptors": properties, "lipinski_rule_of_five": {"violations": violations, "passes": violations <= 1},
            "admet": "NOT RUN · descriptors are not ADMET predictions"}


@app.post("/api/ligands/prepare")
def prepare_ligand(data: LigandPrepareInput) -> dict[str, Any]:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        raise HTTPException(503, "RDKit is not installed; ligand preparation is unavailable")
    molecule = Chem.MolFromSmiles(data.smiles)
    if molecule is None:
        raise HTTPException(422, "RDKit could not parse the supplied SMILES")
    molecule = Chem.AddHs(molecule)
    params = AllChem.ETKDGv3()
    params.randomSeed = data.random_seed
    conformer_id = AllChem.EmbedMolecule(molecule, params)
    if conformer_id < 0:
        raise HTTPException(422, "RDKit could not generate a 3D conformer")
    optimization = AllChem.MMFFOptimizeMolecule(molecule, confId=conformer_id)
    destination = UPLOAD_DIR / f"ligand-{uuid.uuid4().hex}.sdf"
    writer = Chem.SDWriter(str(destination))
    writer.write(molecule, confId=conformer_id)
    writer.close()
    return {"status": "COMPLETED", "path": str(destination), "format": "SDF", "source": "User supplied SMILES",
            "method": "RDKit ETKDGv3 conformer generation; hydrogens added; MMFF optimization attempted",
            "optimization_status": "CONVERGED" if optimization == 0 else "NOT CONVERGED", "random_seed": data.random_seed,
            "note": "SDF output is not AutoDock Vina PDBQT; atom types and charges still require a documented compatible preparation tool."}


@app.post("/api/uploads/ligand")
async def upload_ligand(file: UploadFile = File(...)) -> dict[str, Any]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".sdf", ".mol", ".mol2", ".pdbqt"}:
        raise HTTPException(415, "Supported ligand formats: SDF, MOL, MOL2, PDBQT")
    content = await file.read(20_000_001)
    if len(content) > 20_000_000:
        raise HTTPException(413, "Upload exceeds 20 MB limit")
    if not content.strip():
        raise HTTPException(422, "Uploaded file is empty")
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(content)
    return {"status": "UPLOADED", "filename": Path(file.filename or safe_name).name, "stored_as": safe_name,
            "path": str(dest), "bytes": len(content), "validation": "NOT RUN · install RDKit to parse this format"}


@app.get("/api/integrations")
def integrations() -> dict[str, Any]:
    return {"vina": binary_status("vina"), "gromacs": binary_status("gmx"), "admet": "ADMET ENGINE NOT CONFIGURED",
            "disease_targets": "DATA UNAVAILABLE · no disease-target provider configured", "pdb": "RCSB PDB API configured"}


@app.post("/api/docking/configuration")
def docking_configuration(data: DockingConfig) -> dict[str, Any]:
    for value in (data.protein_path, data.ligand_path):
        path = Path(value).resolve()
        if not path.is_relative_to(DATA_DIR):
            raise HTTPException(422, "Docking inputs must be stored under the configured CADD data directory")
        if not path.is_file():
            raise HTTPException(422, f"Input file does not exist: {path.name}")
        if path.suffix.lower() not in {".pdbqt"}:
            raise HTTPException(422, "Vina inputs must be prepared PDBQT files")
    executable = shutil.which("vina")
    if not executable:
        raise HTTPException(503, "AutoDock Vina is not configured. Install Vina and make its executable available on PATH. No docking was run.")
    config = {"receptor": str(Path(data.protein_path).resolve()), "ligand": str(Path(data.ligand_path).resolve()),
              "center_x": data.center_x, "center_y": data.center_y, "center_z": data.center_z,
              "size_x": data.size_x, "size_y": data.size_y, "size_z": data.size_z, "exhaustiveness": data.exhaustiveness}
    return {"status": "READY", "executable": executable, "configuration": config}


def run_vina_job(job_id: str, config: dict[str, Any]) -> None:
    output = DATA_DIR / "jobs" / job_id
    output.mkdir(parents=True, exist_ok=True)
    pose_path, log_path = output / "poses.pdbqt", output / "vina.log"
    args = [shutil.which("vina") or "vina", "--receptor", config["receptor"], "--ligand", config["ligand"],
            "--center_x", str(config["center_x"]), "--center_y", str(config["center_y"]), "--center_z", str(config["center_z"]),
            "--size_x", str(config["size_x"]), "--size_y", str(config["size_y"]), "--size_z", str(config["size_z"]),
            "--exhaustiveness", str(config["exhaustiveness"]), "--out", str(pose_path), "--log", str(log_path)]
    with connect() as db:
        db.execute("UPDATE jobs SET status='RUNNING',updated_at=? WHERE id=?", (now(), job_id))
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=6 * 60 * 60, check=False)
        log_text = result.stdout + "\n" + result.stderr
        (output / "process.log").write_text(log_text, encoding="utf-8")
        if result.returncode != 0 or not pose_path.exists() or pose_path.stat().st_size == 0:
            raise RuntimeError(f"Vina failed (exit {result.returncode}); inspect process.log")
        vina_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        scores = [float(value) for value in re.findall(r"^\s*\d+\s+(-?\d+(?:\.\d+)?)", log_text + "\n" + vina_log, re.M)]
        if not scores:
            raise RuntimeError("Vina exited successfully but no affinity rows could be parsed")
        payload = {"status": "COMPLETED", "scores_kcal_mol": scores, "pose_file": str(pose_path), "log_file": str(log_path), "source": "AutoDock Vina execution"}
        with connect() as db:
            db.execute("UPDATE jobs SET status='COMPLETED',result=?,updated_at=? WHERE id=?", (json.dumps(payload), now(), job_id))
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE jobs SET status='FAILED',error=?,updated_at=? WHERE id=?", (str(exc), now(), job_id))


@app.post("/api/docking/jobs", status_code=202)
def start_docking(data: DockingConfig, background_tasks: BackgroundTasks, project_id: str | None = None) -> dict[str, Any]:
    config_result = docking_configuration(data)
    config = config_result["configuration"]
    job_id, timestamp = str(uuid.uuid4()), now()
    with connect() as db:
        if project_id and not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)", (job_id, project_id, "vina-docking", "QUEUED", json.dumps(config), None, None, timestamp, timestamp))
    background_tasks.add_task(run_vina_job, job_id, config)
    return {"id": job_id, "status": "QUEUED", "kind": "vina-docking", "configuration": config}


@app.get("/api/jobs")
def jobs() -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC")]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return dict(row)


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    log_path = DATA_DIR / "jobs" / job_id / "process.log"
    return {"job_id": job_id, "status": job["status"], "error": job["error"],
            "log": log_path.read_text(encoding="utf-8") if log_path.exists() else "No process log is available yet."}


@app.get("/api/jobs/{job_id}/poses")
def get_job_poses(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job["status"] != "COMPLETED":
        raise HTTPException(409, f"Docking job is {job['status']}; poses are not available")
    pose_path = DATA_DIR / "jobs" / job_id / "poses.pdbqt"
    if not pose_path.is_file():
        raise HTTPException(404, "Pose file not found")
    return FileResponse(pose_path, media_type="chemical/x-pdbqt", filename="poses.pdbqt")


@app.post("/api/md/jobs")
def md_unavailable() -> dict[str, str]:
    if not shutil.which("gmx"):
        raise HTTPException(503, "DEPENDENCY MISSING: GROMACS executable 'gmx' is not on PATH. No simulation was run.")
    raise HTTPException(501, "GROMACS execution and force-field preparation are not implemented. No simulation was run.")


@app.get("/api/reports/{project_id}")
def report(project_id: str) -> dict[str, Any]:
    return get_project(project_id) | {"limitations": ["No docking results are created unless AutoDock Vina is configured and executed.", "ADMET engine not configured.", "GROMACS execution not connected.", "Experimental validation required."], "generated_at": now()}
