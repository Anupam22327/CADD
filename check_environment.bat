@echo off
setlocal
echo CADD Discovery environment check
python --version
if errorlevel 1 echo Python not found on PATH. Install Python 3.10 or newer.
where python
where vina
if errorlevel 1 echo AutoDock Vina missing: install it and add vina.exe to PATH.
where gmx
if errorlevel 1 echo GROMACS missing: install it and add gmx.exe to PATH.
python -c "import importlib.util as u; print('FastAPI:',bool(u.find_spec('fastapi')),'RDKit:',bool(u.find_spec('rdkit')),'Biopython:',bool(u.find_spec('Bio')))"
endlocal
