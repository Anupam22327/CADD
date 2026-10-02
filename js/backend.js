/* Connects the preserved dashboard to the local API without implying unavailable computations ran. */
(function () {
  'use strict';
  const API = 'http://127.0.0.1:8000/api';
  const banner = document.querySelector('.notice');
  if (!banner) return;
  const message = document.createElement('span');
  message.id = 'backendStatus';
  message.style.marginLeft = '8px';
  banner.querySelector('span:last-of-type')?.append(message);
  fetch(`${API}/health`).then(response => {
    if (!response.ok) throw new Error(`API HTTP ${response.status}`);
    return response.json();
  }).then(info => {
    const rdkit = info.rdkit.status === 'AVAILABLE' ? `RDKit ${info.rdkit.version}` : 'RDKit dependency missing';
    message.textContent = ` Local API connected · ${rdkit} · Vina ${info.vina.status.toLowerCase()} · GROMACS ${info.gromacs.status.toLowerCase()}.`;
    message.dataset.state = 'connected';
  }).catch(() => {
    message.textContent = ' Local API not connected · run setup.bat, then start.bat to enable backend features.';
    message.dataset.state = 'disconnected';
  });
  window.CADD_API = {
    async createProject(project) {
      const response = await fetch(`${API}/projects`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(project) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Project creation failed');
      return data;
    },
    async retrievePdb(id, projectId) {
      const url = `${API}/structures/${encodeURIComponent(id)}${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`;
      const response = await fetch(url, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Structure retrieval failed');
      return data;
    },
    async validateSmiles(name, smiles, projectId) {
      const response = await fetch(`${API}/ligands/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, smiles, project_id: projectId }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Ligand validation failed');
      return data;
    }
  };
  let activeProjectId = null;
  let projectRecords = [];
  const activeName = document.querySelector('#activeProjectName');
  const activeStatus = document.querySelector('#activeProjectStatus');
  const refreshProjects = async () => {
    try {
      const response = await fetch(`${API}/projects`);
      if (!response.ok) throw new Error('Could not load projects');
      projectRecords = await response.json();
      const current = projectRecords[0];
      if (current) {
        activeProjectId = current.id;
        if (activeName) activeName.textContent = current.name;
        if (activeStatus) activeStatus.textContent = current.disease || 'Local research project';
      }
    } catch (_) { /* API connection state is already shown above. */ }
  };
  refreshProjects();
  document.querySelector('.project-switch')?.addEventListener('click', async () => {
    await refreshProjects();
    if (!projectRecords.length) return window.alert('No saved projects yet. Create one first.');
    const menu = projectRecords.map((project, index) => `${index + 1}. ${project.name} — ${project.disease || 'No disease set'}`).join('\n');
    const selected = Number(window.prompt(`Open a saved project by number:\n${menu}`));
    const project = projectRecords[selected - 1];
    if (!project) return;
    activeProjectId = project.id;
    if (activeName) activeName.textContent = project.name;
    if (activeStatus) activeStatus.textContent = project.disease || 'Local research project';
  });
  document.querySelector('#createProjectButton')?.addEventListener('click', async () => {
    const name = window.prompt('Name this research project:');
    if (!name?.trim()) return;
    const disease = window.prompt('Disease or research context (optional):') || '';
    try {
      const project = await window.CADD_API.createProject({ name: name.trim(), disease });
      activeProjectId = project.id;
      if (activeName) activeName.textContent = project.name;
      if (activeStatus) activeStatus.textContent = project.disease || 'Local research project';
      projectRecords.unshift(project);
      window.alert(`Project saved locally: ${project.name}`);
    } catch (error) { window.alert(error.message); }
  });
  document.querySelector('#saveStructureButton')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = 'Retrieving from RCSB…';
    try {
      const structure = await window.CADD_API.retrievePdb(document.querySelector('#pdbInput')?.value, activeProjectId);
      button.textContent = `Saved original PDB ${structure.pdb_id} · ${Math.round(structure.bytes / 1024)} KB`;
      const status = document.querySelector('#analyzeStatus');
      if (status) status.textContent = `Saved ${structure.pdb_id} from RCSB PDB · ${structure.title}`;
    } catch (error) {
      button.textContent = `Save failed · ${error.message}`;
    } finally { button.disabled = false; }
  });
}());
