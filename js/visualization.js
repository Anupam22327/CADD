/* Reusable protein viewer. Scientific structures and metadata are always retrieved live. */
(function () {
  'use strict';

  const RESIDUE_NAMES = {
    ALA:'Alanine', ARG:'Arginine', ASN:'Asparagine', ASP:'Aspartic acid', CYS:'Cysteine',
    GLN:'Glutamine', GLU:'Glutamic acid', GLY:'Glycine', HIS:'Histidine', ILE:'Isoleucine',
    LEU:'Leucine', LYS:'Lysine', MET:'Methionine', PHE:'Phenylalanine', PRO:'Proline',
    SER:'Serine', THR:'Threonine', TRP:'Tryptophan', TYR:'Tyrosine', VAL:'Valine'
  };

  class MolecularExplorer {
    constructor(options) {
      this.options = options;
      this.element = document.querySelector(options.viewer);
      this.viewer = null;
      this.model = null;
      this.defaultView = null;
      this.pdbTextCache = new Map();
      this.pdbId = null;
      this.data = { proteinData: null, bindingSiteData: null, ligandData: null, dockingData: null, admetData: null, mdData: null };
      this.representation = 'cartoon';
      this.mode = 'protein';
      this.abortController = null;
      this.loadingId = null;
      this.resizeObserver = null;
      this.loaded = false;
      this.bindControls();
      this.createViewer();
      this.loadProteinStructure(options.pdbId || '1BVR');
    }

    createViewer() {
      if (!this.element) return this.fail('Viewer container was not found.');
      if (!window.$3Dmol || typeof window.$3Dmol.createViewer !== 'function') {
        return this.fail('3Dmol.js could not be loaded. Check the CDN connection and reload.');
      }
      try {
        this.viewer = window.$3Dmol.createViewer(this.element, {
          backgroundColor: '#f3f7f4', antialias: true
        });
        this.viewer.setBackgroundColor('#f3f7f4');
        if (window.ResizeObserver) {
          this.resizeObserver = new ResizeObserver(() => this.resize());
          this.resizeObserver.observe(this.element);
        } else {
          window.addEventListener('resize', this.onResize = () => this.resize());
        }
      } catch (error) {
        this.fail(`Viewer initialization failed: ${error.message}`);
      }
    }

    bindControls() {
      document.querySelectorAll('[data-style]').forEach(button => button.addEventListener('click', () => {
        this.setRepresentation(button.dataset.style);
      }));
      document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
        this.setMode(button.dataset.view);
      }));
      const input = document.querySelector('#pdbInput');
      const loadButton = document.querySelector('#loadPdbButton');
      if (loadButton) loadButton.addEventListener('click', () => this.loadProteinStructure(input.value));
      if (input) input.addEventListener('keydown', event => {
        if (event.key === 'Enter') this.loadProteinStructure(input.value);
      });
      const reset = document.querySelector('#resetView');
      if (reset) reset.addEventListener('click', () => this.reset());
      const fit = document.querySelector('#fitView');
      if (fit) fit.addEventListener('click', () => this.fit());
      const fullscreen = document.querySelector('#fullscreen');
      if (fullscreen) fullscreen.addEventListener('click', () => this.toggleFullscreen());
    }

    async loadProteinStructure(pdbId) {
      const id = String(pdbId || '').trim().toUpperCase();
      if (!/^[A-Z0-9]{4}$/.test(id)) {
        this.fail(id ? 'Invalid PDB ID. Enter a four-character accession.' : 'Enter a PDB ID to load a structure.');
        return false;
      }
      if (!this.viewer) {
        this.fail('The molecular viewer is unavailable. Check that 3Dmol.js loaded.');
        return false;
      }
      if (this.loaded && this.pdbId === id) {
        this.setMode('protein');
        this.fit();
        this.setStatus('loaded', `Structure loaded · PDB ${id}`, 'Available');
        return true;
      }
      if (this.loadingId === id) return false;
      this.abortController?.abort();
      this.abortController = new AbortController();
      this.loadingId = id;
      this.setStatus('loading', `Loading structure · PDB ${id}…`, 'Checking…');
      const overlay = document.querySelector('#viewerState');
      if (overlay) {
        overlay.innerHTML = '<span class="loader"></span><b>Loading structure…</b><small>Retrieving coordinates from RCSB PDB</small>';
        overlay.classList.remove('hidden');
      }
      this.loaded = false;
      try {
        let pdbText = this.pdbTextCache.get(id);
        if (!pdbText) {
          const response = await fetch(`https://files.rcsb.org/download/${id}.pdb`, {
            signal: this.abortController.signal
          });
          if (!response.ok) throw new Error(`RCSB PDB returned HTTP ${response.status}.`);
          pdbText = await response.text();
          if (!/^ATOM  |^HEADER|^TITLE /m.test(pdbText)) throw new Error('The response did not contain a valid PDB structure.');
          this.pdbTextCache.set(id, pdbText);
        }
        this.viewer.clear();
        this.model = this.viewer.addModel(pdbText, 'pdb');
        const atoms = this.model.selectedAtoms({});
        if (!atoms || atoms.length === 0) throw new Error('No atoms were found in the downloaded structure.');
        this.pdbId = id;
        if (this.data.bindingSiteData?.pdbId !== id) this.data.bindingSiteData = null;
        document.querySelector('#residueSelection')?.classList.add('hidden');
        this.data.proteinData = { pdbId: id, title: (pdbText.match(/^TITLE\s+\d*\s*(.*)$/m) || [])[1]?.trim() || '', atoms };
        this.applyRepresentation();
        this.enableResidueSelection();
        this.viewer.zoomTo();
        this.viewer.render();
        this.defaultView = this.viewer.getView?.() || null;
        this.loaded = true;
        this.setMode('protein');
        this.setStatus('loaded', `Structure loaded · PDB ${id}`, 'Available');
        this.updateStructureInfo(id, atoms, pdbText);
        if (this.loadingId === id) this.loadingId = null;
        if (overlay) overlay.classList.add('hidden');
        const input = document.querySelector('#pdbInput');
        if (input) input.value = id;
        return true;
      } catch (error) {
        if (error.name === 'AbortError') return false;
        console.error('Protein structure load failed:', error);
        this.viewer?.clear();
        this.viewer?.render();
        this.model = null;
        this.pdbId = null;
        this.loaded = false;
        this.fail(`Unable to load PDB structure. ${error.message} Please check the PDB ID or your internet connection.`);
        if (this.loadingId === id) this.loadingId = null;
        return false;
      }
    }

    applyRepresentation() {
      if (!this.viewer || !this.loaded && !this.model) return;
      this.viewer.removeAllSurfaces();
      const styles = {
        cartoon: { cartoon: { color: 'spectrum', opacity: 0.96 } },
        stick: { stick: { colorscheme: 'chain', radius: 0.18 } },
        sphere: { sphere: { colorscheme: 'chain', scale: 0.28 } },
        surface: { cartoon: { color: 'spectrum', opacity: 0.25 } }
      };
      this.viewer.setStyle({}, styles[this.representation] || styles.cartoon);
      if (this.representation === 'surface') {
        this.viewer.addSurface(window.$3Dmol.SurfaceType.VDW, { opacity: 0.68, colorscheme: 'whiteCarbon' }, {});
      }
      this.viewer.render();
      document.querySelectorAll('[data-style]').forEach(button => {
        button.classList.toggle('active', button.dataset.style === this.representation);
        button.setAttribute('aria-pressed', button.dataset.style === this.representation ? 'true' : 'false');
      });
      const caption = document.querySelector('#viewerCaption');
      if (caption) caption.textContent = `${this.pdbId || 'Protein'} · ${this.representation} representation`;
    }

    setRepresentation(style) {
      if (!['cartoon', 'surface', 'stick', 'sphere'].includes(style)) return;
      if (!this.loaded) return this.showMessage('Load a valid structure before changing its representation.');
      this.representation = style;
      this.applyRepresentation();
      this.setMode('protein', false);
    }

    setMode(mode, updateTabs = true) {
      if (!['protein', 'pocket', 'complex', 'interactions'].includes(mode)) return;
      this.mode = mode;
      if (updateTabs) document.querySelectorAll('[data-view]').forEach(button => {
        button.classList.toggle('selected', button.dataset.view === mode);
        button.setAttribute('aria-selected', button.dataset.view === mode ? 'true' : 'false');
      });
      const modeLabel = document.querySelector('#viewerMode');
      if (modeLabel) modeLabel.textContent = mode === 'protein' ? 'Protein' : mode === 'pocket' ? 'Binding pocket' : 'Not run';
      const caption = document.querySelector('#viewerCaption');
      const overlay = document.querySelector('#viewerState');
      if (mode === 'complex' || mode === 'interactions') {
        const message = mode === 'complex'
          ? ['Docking not run', 'Docked complex will become available after an actual docking calculation is performed.']
          : ['Interaction analysis unavailable', 'Interaction analysis is unavailable until a protein–ligand complex is generated.'];
        if (overlay) {
          overlay.innerHTML = `<b>${message[0]}</b><small>${message[1]}</small>`;
          overlay.classList.remove('hidden');
        }
        if (caption) caption.textContent = message[0];
        return;
      }
      if (mode === 'pocket') {
        if (this.loaded) {
          this.applyRepresentation();
          const site = this.data.bindingSiteData;
          if (site?.residues?.length && site.source && site.pdbId === this.pdbId) {
            const residues = site.residues.filter(item => Number.isInteger(Number(item.position)));
            if (residues.length) {
              residues.forEach(item => this.viewer.addStyle(
                { resi: Number(item.position), ...(item.chain ? { chain: item.chain } : {}) },
                { stick: { colorscheme: 'orangeCarbon', radius: 0.24 } }
              ));
              this.viewer.render();
              if (overlay) {
                overlay.innerHTML = `<b>Binding-site reference · ${residues.length} residues</b><small>Source: ${this.escapeText(site.source)}</small>`;
                overlay.classList.remove('hidden');
              }
              if (caption) caption.textContent = `Binding pocket · source: ${site.source}`;
              return;
            }
          }
        }
        if (overlay) {
          overlay.innerHTML = '<b>Binding-site residue data not connected yet</b><small>No verified pocket residues are available to highlight.</small>';
          overlay.classList.remove('hidden');
        }
        if (caption) caption.textContent = 'Binding pocket · residue data not connected';
        return;
      }
      if (this.loaded) {
        this.applyRepresentation();
        if (overlay) overlay.classList.add('hidden');
      }
      if (caption) caption.textContent = `${this.pdbId || 'Protein'} · ${this.representation} representation`;
    }

    setBindingSiteData(bindingSiteData) {
      this.data.bindingSiteData = bindingSiteData && Array.isArray(bindingSiteData.residues) && bindingSiteData.source && bindingSiteData.pdbId
        ? bindingSiteData : null;
      if (this.mode === 'pocket') this.setMode('pocket');
    }

    escapeText(value) {
      const span = document.createElement('span');
      span.textContent = String(value);
      return span.innerHTML;
    }

    enableResidueSelection() {
      if (!this.viewer) return;
      this.viewer.setClickable({}, true, atom => {
        if (!atom || !atom.resi || !atom.resn) return;
        const name = RESIDUE_NAMES[atom.resn] || 'Unspecified';
        const details = document.querySelector('#residueSelection');
        if (details) {
          details.innerHTML = `<b>${atom.resn}${atom.resi}</b><span>Position ${atom.resi} · Chain ${atom.chain || '—'} · ${name}</span>`;
          details.classList.remove('hidden');
        }
        this.applyRepresentation();
        this.viewer.addStyle({ chain: atom.chain, resi: atom.resi }, { stick: { colorscheme: 'yellowCarbon', radius: 0.24 } });
        this.viewer.render();
      });
    }

    async updateStructureInfo(id, atoms, pdbText) {
      const titleMatch = pdbText.match(/^TITLE\s+\d*\s*(.*)$/m);
      const title = titleMatch ? titleMatch[1].trim() : 'Protein structure';
      const chains = [...new Set(atoms.map(atom => atom.chain).filter(Boolean))].sort();
      this.setText('#proteinName', title || 'Protein structure');
      this.setText('#geneName', 'Metadata loading…');
      this.setText('#pdbName', id);
      this.setText('#organismName', 'Metadata loading…');
      this.setText('#chainName', chains.length ? chains.join(', ') : 'Not reported');
      const link = document.querySelector('#pdbSourceLink');
      if (link) { link.href = `https://www.rcsb.org/structure/${id}`; link.textContent = `RCSB PDB · ${id} ↗`; }
      const sourceId = document.querySelector('#structureSource');
      if (sourceId) sourceId.textContent = 'RCSB PDB';
      const type = document.querySelector('#structureType');
      if (type) type.textContent = 'PDB structure';
      const titleEl = document.querySelector('#pdbTitle');
      if (titleEl) titleEl.textContent = title;
      try {
        const response = await fetch(`https://data.rcsb.org/rest/v1/core/entry/${id}`);
        if (!response.ok) {
          this.setText('#organismName', 'Metadata unavailable');
          this.setText('#geneName', 'Metadata unavailable');
          return;
        }
        const metadata = await response.json();
        const method = metadata.exptl?.map(item => item.method).filter(Boolean).join(', ');
        if (method) this.setText('#structureType', method);
        const entityIds = metadata.rcsb_entry_container_identifiers?.polymer_entity_ids || [];
        const entityRecords = await Promise.all(entityIds.map(async entityId => {
          const entityResponse = await fetch(`https://data.rcsb.org/rest/v1/core/polymer_entity/${id}/${entityId}`);
          return entityResponse.ok ? entityResponse.json() : null;
        }));
        const authChains = new Set(chains);
        const entity = entityRecords.filter(Boolean).find(record =>
          record.rcsb_polymer_entity_container_identifiers?.auth_asym_ids?.some(chain => authChains.has(chain))
        ) || entityRecords.find(Boolean);
        const organisms = entity?.rcsb_entity_source_organism?.map(item => item.ncbi_scientific_name).filter(Boolean);
        const genes = entity?.rcsb_entity_source_organism?.flatMap(item => item.rcsb_gene_name?.map(gene => gene.value) || []).filter(Boolean);
        this.setText('#organismName', organisms?.length ? organisms.join(', ') : 'Not available in entity metadata');
        this.setText('#geneName', genes?.length ? genes.join(', ') : 'Not available in entity metadata');
        if (entity?.rcsb_polymer_entity?.pdbx_description) this.setText('#proteinName', entity.rcsb_polymer_entity.pdbx_description);
      } catch (_) {
        this.setText('#organismName', 'Metadata unavailable');
        this.setText('#geneName', 'Metadata unavailable');
      }
    }

    setStatus(state, message, connection) {
      const status = document.querySelector('#structureStatus');
      if (status) {
        status.dataset.state = state;
        status.innerHTML = `<span class="status-indicator"></span>${message}`;
      }
      this.setText('#connectionStatus', connection);
      this.setText('#viewerMode', this.mode === 'protein' ? 'Protein' : this.mode);
    }

    setText(selector, value) {
      const element = document.querySelector(selector);
      if (element) element.textContent = value;
    }

    showMessage(message) {
      const overlay = document.querySelector('#viewerState');
      if (overlay) { overlay.innerHTML = `<b>${message}</b>`; overlay.classList.remove('hidden'); }
    }

    fail(message) {
      this.setStatus('unavailable', 'Structure unavailable', 'Unavailable');
      this.showMessage(message);
    }

    fit() { if (this.loaded) { this.viewer.zoomTo(); this.viewer.render(); } }
    reset() {
      if (!this.loaded) return;
      this.mode = 'protein';
      this.representation = 'cartoon';
      this.setMode('protein');
      if (this.defaultView && this.viewer.setView) this.viewer.setView(this.defaultView);
      this.viewer.zoomTo();
      this.viewer.render();
    }
    resize() { if (this.viewer && this.loaded) { this.viewer.resize(); this.viewer.render(); } }
    toggleFullscreen() {
      const panel = document.querySelector('.molecule-card');
      if (!document.fullscreenElement) panel?.requestFullscreen?.(); else document.exitFullscreen?.();
      setTimeout(() => this.resize(), 100);
    }
    destroy() {
      this.abortController?.abort();
      this.resizeObserver?.disconnect();
      if (this.onResize) window.removeEventListener('resize', this.onResize);
      this.viewer?.clear();
      this.viewer = null;
    }
  }

  window.MolecularExplorer = MolecularExplorer;
  window.loadProteinStructure = pdbId => window.molecularExplorer
    ? window.molecularExplorer.loadProteinStructure(pdbId)
    : Promise.resolve(false);
  window.setBindingSiteData = data => window.molecularExplorer?.setBindingSiteData(data);
  document.addEventListener('DOMContentLoaded', () => {
    window.molecularExplorer = new MolecularExplorer({ viewer: '#molviewer', pdbId: '1BVR' });
  }, { once: true });
}());
