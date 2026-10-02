import unittest
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app, connect


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_reports_real_dependency_states(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertIn(response.json()["vina"]["status"], {"AVAILABLE", "DEPENDENCY MISSING"})

    def test_project_create_and_retrieve(self):
        response = self.client.post("/api/projects", json={"name": "API test project", "disease": "Test"})
        self.assertEqual(response.status_code, 201)
        project = response.json()
        try:
            loaded = self.client.get(f"/api/projects/{project['id']}")
            self.assertEqual(loaded.status_code, 200)
            self.assertEqual(loaded.json()["name"], "API test project")
        finally:
            with connect() as db:
                db.execute("DELETE FROM projects WHERE id=?", (project["id"],))

    def test_rdkit_descriptors(self):
        response = self.client.post("/api/ligands/validate", json={"name": "ethanol", "smiles": "CCO"})
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json()["descriptors"]["molecular_weight"], 46.069, places=3)
        self.assertEqual(response.json()["admet"], "NOT RUN · descriptors are not ADMET predictions")

    def test_invalid_smiles_and_pdb_accession(self):
        ligand = self.client.post("/api/ligands/validate", json={"smiles": "not-a-smiles"})
        pdb = self.client.post("/api/structures/bad")
        self.assertEqual(ligand.status_code, 422)
        self.assertEqual(pdb.status_code, 422)

    def test_upload_validation(self):
        response = self.client.post("/api/uploads/ligand", files={"file": ("bad.exe", b"x")})
        self.assertEqual(response.status_code, 415)

    def test_job_and_configuration_errors(self):
        missing_job = self.client.get("/api/jobs/not-a-job")
        invalid_config = self.client.post("/api/docking/configuration", json={
            "protein_path": "missing.pdbqt", "ligand_path": "missing-ligand.pdbqt",
            "center_x": 0, "center_y": 0, "center_z": 0,
            "size_x": 20, "size_y": 20, "size_z": 20,
        })
        self.assertEqual(missing_job.status_code, 404)
        self.assertEqual(invalid_config.status_code, 422)


if __name__ == "__main__":
    unittest.main()
