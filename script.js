const API = "http://127.0.0.1:8000"; 
let map = L.map('map', { zoomControl: false }).setView([20.5937, 78.9629], 5);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
let mapLayers = [];

window.activeSimId = null;
window.currentTab = 'dashboard';

window.onload = async () => {
    try {
        const r = await fetch(`${API}/config`); const conf = await r.json();
        const locSelects = [document.getElementById('start'), document.getElementById('destination'), document.getElementById('autoStart'), document.getElementById('autoDest')];
        conf.states.forEach(s => locSelects.forEach(sel => { if(sel) sel.add(new Option(s, s)); }));
        document.getElementById('start').value = "Assam"; document.getElementById('destination').value = "Karnataka"; 
        document.getElementById('autoStart').value = "Maharashtra"; document.getElementById('autoDest').value = "Tamil Nadu";
        
        const populate = (id, arr) => { let el = document.getElementById(id); if(el) arr.forEach(opt => el.add(new Option(opt, opt))); }
        populate('cargoClass', conf.cargo_classes); populate('autoCargo', conf.cargo_classes);
        populate('vehicle', conf.vehicles);
        populate('weather', conf.weather_options); populate('traffic', conf.traffic_options); populate('breakdownSim', conf.breakdown_options);
        
        await syncUI(); 
        setTimeout(() => { map.invalidateSize(); }, 500);
    } catch(e) { console.error("Setup Error", e); }
};

function switchTab(tabName) {
    window.currentTab = tabName;
    document.getElementById('tab-dashboard').classList.toggle('hidden', tabName !== 'dashboard');
    document.getElementById('tab-simulator').classList.toggle('hidden', tabName !== 'simulator');
    document.getElementById('btn-tab-dashboard').className = (tabName === 'dashboard') ? "bg-blue-600 text-white px-6 py-3 rounded-xl font-black uppercase tracking-widest text-xs transition-all" : "bg-slate-800 text-slate-400 hover:text-white px-6 py-3 rounded-xl font-black uppercase tracking-widest text-xs transition-all";
    document.getElementById('btn-tab-simulator').className = (tabName === 'simulator') ? "bg-blue-600 text-white px-6 py-3 rounded-xl font-black uppercase tracking-widest text-xs transition-all" : "bg-slate-800 text-slate-400 hover:text-white px-6 py-3 rounded-xl font-black uppercase tracking-widest text-xs transition-all";
    syncUI();
}

function selectSim(id) { window.activeSimId = id; syncUI(); }

async function simTimeSkip(action) { 
    if(window.activeSimId) { await apiPost(`/simulator/time-skip/${window.activeSimId}`, { action: action }); }
}

async function simInjectEvent() { 
    if(!window.activeSimId) return; 
    await apiPost(`/simulator/inject/${window.activeSimId}`, { weather: document.getElementById('simWeather').value, traffic: document.getElementById('simTraffic').value, breakdown: document.getElementById('simBreakdown').value }); 
}

async function fetchTargetTemp() {
    const d = await apiPost('/calc-temp', {cargo_class: document.getElementById('cargoClass').value, weather: document.getElementById('weather').value});
    if(d) {
        let t = document.getElementById('targetTemp'); let s = document.getElementById('iotStatusLabel');
        t.value = d.target_temp; t.className = "w-full bg-transparent font-black text-xl outline-none transition-colors " + (d.status_type==='cooling'?'text-blue-400':d.status_type==='heating'?'text-rose-400':d.status_type==='eco'?'text-emerald-400':'text-slate-300');
        s.innerHTML = d.status_type==='cooling'?`<span class='text-blue-400'>Cooling (${d.ambient}°)</span>`:d.status_type==='heating'?`<span class='text-rose-400'>Heating (${d.ambient}°)</span>`:`<span class='text-slate-400'>Ambient</span>`;
    }
}

function autoSelectVehicle() {
    const cargo = document.getElementById('cargoClass').value.toLowerCase();
    const weight = parseFloat(document.getElementById('weight').value);
    let vSelect = document.getElementById('vehicle');
    
    if(cargo.includes('nitrogen') || cargo.includes('perishable') || cargo.includes('pharma')) { vSelect.value = "Refrigerated Truck (Reefer)"; } 
    else if (weight > 10000 || cargo.includes('construction')) { vSelect.value = "Heavy Truck (18-Wheeler)"; } 
    else { vSelect.value = "Medium Truck (Eicher)"; }
    
    vSelect.classList.add('bg-blue-600/30', 'border-blue-400');
    setTimeout(() => { vSelect.classList.remove('bg-blue-600/30', 'border-blue-400'); }, 500);
}

function getPayload() {
    return { 
        start: document.getElementById('start').value, 
        destination: document.getElementById('destination').value, 
        vehicle: document.getElementById('vehicle').value, 
        weight: parseFloat(document.getElementById('weight').value), 
        cargo_class: document.getElementById('cargoClass').value, 
        traffic: document.getElementById('traffic').value, 
        weather: document.getElementById('weather').value, 
        breakdown_sim: document.getElementById('breakdownSim').value,
        customer_address: "Manual Dispatch Node",
        target_temp: parseFloat(document.getElementById('targetTemp').value)
    };
}

async function loadAgent(id) { 
    await apiPost(`/action/load/${id}`); 
}

async function createSingleShipment() { await apiPost('/create-shipment', getPayload()); }
async function pushToBackendQueue() { await apiPost('/queue/add', getPayload()); }
async function executeBackendQueue(modeStr) { await apiPost('/queue/execute', { mode: modeStr }); }

function fillCommand(cmd) {
    const input = document.getElementById('aiPrompt');
    input.value = cmd;
    input.focus();
}

async function apiPost(endpoint, payload = {}) {
    try {
        const res = await fetch(`${API}${endpoint}`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
        if(!res.ok) return null;
        await syncUI(); 
        return await res.json();
    } catch(e) { return null; }
}

async function syncUI() {
    try {
        const res = await fetch(`${API}/ui-state`, { 
            method: "POST", 
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ active_sim_id: window.activeSimId }) 
        }); 
        const state = await res.json();
        
        document.getElementById('logBody').innerHTML = state.table_html;
        document.getElementById('dispatchPlanCards').innerHTML = state.monitors_html;
        
        const qc = document.getElementById('queueCounter');
        if (qc) qc.innerText = state.queue_count || 0;
        
        const monitorSection = document.getElementById('dispatchPlanSection');
        state.monitors_html === "" ? monitorSection.classList.add('hidden') : monitorSection.classList.remove('hidden');

        if (document.getElementById('simList')) document.getElementById('simList').innerHTML = state.sim_list_html;
        if (document.getElementById('simPanel')) document.getElementById('simPanel').innerHTML = state.sim_panel_html;
        
        drawMap(state.map_data);
    } catch(e) {}
}

async function clearHistory() {
    if(confirm("Are you sure you want to Purge all Logs? This cannot be undone.")) {
        await fetch(`${API}/clear-history`, { method: "DELETE" });
        location.reload();
    }
}

function openAutoModal() { document.getElementById('autoModal').classList.remove('hidden'); }
function closeAutoModal() { document.getElementById('autoModal').classList.add('hidden'); }

async function launchAutomatedFleet() { 
    closeAutoModal();
    const payload = {
        start: document.getElementById('autoStart').value,
        destination: document.getElementById('autoDest').value,
        cargo_class: document.getElementById('autoCargo').value,
        weight: parseFloat(document.getElementById('autoWeight').value)
    };
    
    const res = await fetch(`${API}/action/auto-fleet`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
    const data = await res.json();
    
    if(data.proposals) {
        const section = document.getElementById('proposalSection');
        const container = document.getElementById('proposalCards');
        section.classList.remove('hidden');
        container.innerHTML = '';
        
        data.proposals.forEach(p => {
            const isFast = p.strategy.includes('Alpha');
            const color = isFast ? 'cyan' : 'emerald';
            container.innerHTML += `
                <div class="bg-[#161b2b] border border-${color}-500/50 p-6 rounded-[2rem] shadow-xl relative overflow-hidden">
                    <div class="absolute top-0 left-0 w-full h-1 bg-${color}-500"></div>
                    <div class="flex justify-between items-start mb-4">
                        <span class="text-[10px] font-black uppercase px-3 py-1 rounded-full bg-${color}-500/20 text-${color}-400">${p.strategy}</span>
                        <span class="text-white font-mono text-xs">${p.id}</span>
                    </div>
                    <div class="mb-6 border-b border-slate-800 pb-4">
                        <p class="text-2xl font-black text-white italic uppercase">${p.vehicle}</p>
                        <p class="text-slate-400 text-sm font-bold mt-1">${p.cargo_class} | ${p.origin} to ${p.destination}</p>
                    </div>
                    <div class="flex justify-between mb-6">
                        <div><p class="text-[10px] text-slate-500 font-black uppercase">ETA</p><p class="text-xl font-black text-${color}-400">${p.eta}</p></div>
                        <div class="text-right"><p class="text-[10px] text-slate-500 font-black uppercase">Cost</p><p class="text-xl font-black text-white">${p.cost}</p></div>
                    </div>
                    <button onclick="confirmProposal('${p.id}')" class="w-full py-4 rounded-xl font-black uppercase text-xs tracking-widest transition-all bg-${color}-600 hover:bg-${color}-500 text-white shadow-lg">Confirm & Dispatch</button>
                </div>
            `;
        });
    }
}

async function confirmProposal(id) {
    await fetch(`${API}/action/confirm-proposal/${id}`, { method: "POST" });
    document.getElementById('proposalSection').classList.add('hidden');
    await syncUI();
}

function drawMap(mapData) {
    map.invalidateSize(); mapLayers.forEach(l => map.removeLayer(l)); mapLayers = []; let b = L.latLngBounds();
    mapData.forEach(m => {
        if (m.status === 'DELIVERED' && m.id !== window.activeSimId) return;

        let line = L.polyline(m.coords, { color: m.color, weight: m.weight, dashArray: m.dash, className: 'route-glow', opacity: 0.6 }).addTo(map);
        let sMark = L.circleMarker(m.coords[0], {color: m.color, radius: 4}).addTo(map);
        let eMark = L.circleMarker(m.coords[1], {color: m.color, radius: 4}).addTo(map);
        mapLayers.push(line, sMark, eMark); b.extend(line.getBounds());

        if(m.progress >= 0 && m.progress <= 100 && m.status !== 'DELIVERED' && m.status !== 'CANCELLED') {
            let lat = m.coords[0][0] + (m.coords[1][0] - m.coords[0][0]) * (m.progress / 100);
            let lng = m.coords[0][1] + (m.coords[1][1] - m.coords[0][1]) * (m.progress / 100);
            let icon = L.divIcon({ className: 'c-icon', html: `<div style="background:${m.color}; width:16px; height:16px; border-radius:50%; box-shadow: 0 0 10px ${m.color}; display:flex; align-items:center; justify-content:center;"><i class="fas fa-truck text-[8px] text-white"></i></div>`, iconSize: [16, 16] });
            mapLayers.push(L.marker([lat, lng], {icon: icon}).addTo(map));
        }

        if (m.alert) {
            let aMark = L.circleMarker(m.alert.coords, {color: m.alert.color, fillOpacity: 0.8, radius: 10, className: m.alert.class}).addTo(map).bindPopup(m.alert.popup).openPopup();
            mapLayers.push(aMark);
        }
    });
    if(b.isValid()) map.fitBounds(b, { padding: [50, 50] });
}

setInterval(() => {
    const now = new Date().getTime();
    document.querySelectorAll('.live-clock').forEach(el => {
        const iso = el.getAttribute('data-target-time'); const st = el.getAttribute('data-status');
        if (!iso || st === 'CANCELLED' || st === 'DELIVERED') {
            if (st === 'DELIVERED') el.innerText = "ARRIVED";
            return;
        }
        if (st === 'CARGO STOLEN') { el.innerText = "SIGNAL LOST"; return; }
        if (st === 'CRITICAL FAILURE') { el.innerText = "HALTED"; return; }
        
        const diff = new Date(iso).getTime() - now;
        if (diff <= 0) { el.innerText = "ARRIVED / WAITING"; return; }
        const h = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60)).toString().padStart(2, '0');
        const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60)).toString().padStart(2, '0');
        const s = Math.floor((diff % (1000 * 60)) / 1000).toString().padStart(2, '0');
        el.innerText = `${h}:${m}:${s}`;
    });
    document.querySelectorAll('.progress-bar').forEach(bar => {
        const s = bar.getAttribute('data-start'); const e = bar.getAttribute('data-end');
        if(!s || !e) return;
        const total = new Date(e).getTime() - new Date(s).getTime(); const elapsed = now - new Date(s).getTime();
        bar.style.width = Math.max(0, Math.min((elapsed / total) * 100, 100)) + "%";
    });
}, 1000);

async function runAIAgent() {
    const promptInput = document.getElementById('aiPrompt');
    const responseBox = document.getElementById('aiResponse');
    const prompt = promptInput.value.trim();
    if (!prompt) return;

    responseBox.classList.remove('hidden');
    responseBox.className = "mt-4 text-sm font-mono text-cyan-400 p-4 bg-[#02050d] rounded-xl border border-cyan-900/50";
    responseBox.innerHTML = '<i class="fas fa-circle-notch fa-spin mr-2"></i> Analyzing Command...';

    try {
        const res = await fetch(`${API}/ai-agent`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: prompt })
        });
        const data = await res.json();
        
        if (res.ok) {
            if (data.status === "error") {
                responseBox.className = "mt-4 text-sm font-mono text-rose-400 p-4 bg-[#02050d] rounded-xl border border-rose-900/50";
                responseBox.innerHTML = `<i class="fas fa-exclamation-triangle mr-2"></i> <b>System Alert:</b> ${data.message}`;
            } else {
                responseBox.className = "mt-4 text-sm font-mono text-emerald-400 p-4 bg-[#02050d] rounded-xl border border-emerald-900/50 leading-relaxed";
                responseBox.innerHTML = `<i class="fas fa-terminal mr-2 mb-2 block"></i> ${data.message}`;
                promptInput.value = ''; 
                await syncUI(); 
            }
        } else {
            throw new Error("Command Failed");
        }
    } catch (e) {
        responseBox.className = "mt-4 text-sm font-mono text-rose-400 p-4 bg-[#02050d] rounded-xl border border-rose-900/50";
        responseBox.innerHTML = `<i class="fas fa-exclamation-triangle mr-2"></i> Network Error: ${e.message}`;
    }
}