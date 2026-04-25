import os
import json
import math
import random
import joblib
import pandas as pd
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="LogiTrack | Enterprise Control Tower")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- DATABASE & MODELS ---
HISTORY_FILE = "shipment_history.json"
PENDING_QUEUE = []
PROPOSAL_DB = {}
agent_sessions = {"pending_options": None}

models = {}
for name in ['eta_variation_hours', 'Dynamic_Shipping_Cost', 'Cargo_Damage_Score']:
    try: models[name] = joblib.load(f"models/{name}_model.pkl")
    except: pass

STATE_COORDS = { "Andhra Pradesh": (15.91, 79.74), "Arunachal Pradesh": (28.21, 94.72), "Assam": (26.20, 92.93), "Bihar": (25.09, 85.31), "Chhattisgarh": (21.27, 81.86), "Goa": (15.29, 74.12), "Gujarat": (22.25, 71.19), "Haryana": (29.05, 76.08), "Himachal Pradesh": (31.10, 77.17), "Jharkhand": (23.61, 85.27), "Karnataka": (15.31, 75.71), "Kerala": (10.85, 76.27), "Madhya Pradesh": (22.97, 78.65), "Maharashtra": (19.75, 75.71), "Manipur": (24.66, 93.90), "Meghalaya": (25.46, 91.36), "Mizoram": (23.16, 92.93), "Nagaland": (26.15, 94.56), "Odisha": (20.95, 85.09), "Punjab": (31.14, 75.34), "Rajasthan": (27.02, 74.21), "Sikkim": (27.53, 88.51), "Tamil Nadu": (11.12, 78.65), "Telangana": (18.11, 79.01), "Tripura": (23.94, 91.98), "Uttar Pradesh": (26.84, 80.94), "Uttarakhand": (30.06, 79.01), "West Bengal": (22.98, 87.85), "Delhi": (28.61, 77.20) }
VEHICLES = { "Mini Truck (Tata Ace)": {"speed": 50, "vol": 1.2, "mode": "Road", "cat": "Medium", "rate": 0.08}, "Medium Truck (Eicher)": {"speed": 55, "vol": 1.1, "mode": "Road", "cat": "Medium", "rate": 0.045}, "Heavy Truck (18-Wheeler)": {"speed": 45, "vol": 1.0, "mode": "Road", "cat": "Slow", "rate": 0.04}, "Hydraulic Trailer (ODC)": {"speed": 30, "vol": 1.5, "mode": "Road", "cat": "Slow", "rate": 0.08}, "Refrigerated Truck (Reefer)": {"speed": 45, "vol": 1.1, "mode": "Road", "cat": "Medium", "rate": 0.06}, "Freight Train (BCN Wagon)": {"speed": 40, "vol": 1.0, "mode": "Rail", "cat": "Slow", "rate": 0.015}, "Freight Train (BTPN Tank)": {"speed": 40, "vol": 1.0, "mode": "Rail", "cat": "Slow", "rate": 0.02}, "Cargo Plane (Express)": {"speed": 800, "vol": 2.0, "mode": "Air", "cat": "Fast", "rate": 0.40}, "Heavy Cargo Aircraft (HCA)": {"speed": 850, "vol": 1.8, "mode": "Air", "cat": "Fast", "rate": 0.35} }
CARGO_IDEAL_TEMPS = { "General Objects": None, "Pharmaceuticals": 5, "Perishables": -2, "Electronics": 20, "Chemicals: Liquid Nitrogen": -196, "Chemicals: Sulfuric Acid": 20, "Chemicals: Lithium Batteries": 15, "High-Value Goods": 22, "Live Animals": 24, "Construction Materials": None }
WEATHER_AMBIENT_TEMPS = { "Extremely Cold": -15, "Cold": 5, "Rainy": 18, "Sunny": 25, "Hot": 35, "Extremely Hot": 45, "Stormy": 20 }
QUEUE_COLORS = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ec4899', '#06b6d4', '#eab308', '#14b8a6']

class ShipmentRequest(BaseModel):
    start: str; destination: str; vehicle: str; weight: float; cargo_class: str
    target_temp: Optional[float] = None; handling: List[str] = []
    traffic: str = "Clear"; weather: str = "Sunny"; breakdown_sim: str = "None"
    customer_address: str = "N/A"

class AICommandRequest(BaseModel): prompt: str

class UIStateRequest(BaseModel): active_sim_id: Optional[str] = None

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371; a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2-lon1)/2)**2
    return round(R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a))))

def rw_history(mode, data=None):
    if mode == "r":
        if not os.path.exists(HISTORY_FILE): return []
        with open(HISTORY_FILE, "r") as f: return json.load(f)
    else:
        with open(HISTORY_FILE, "w") as f: json.dump(data, f, indent=4)

def suggest_vehicle(cargo, weight, strategy="safe"):
    cargo_lower = cargo.lower()
    if "nitrogen" in cargo_lower or "perishable" in cargo_lower or "pharma" in cargo_lower:
        return "Cargo Plane (Express)" if strategy == "fast" else "Refrigerated Truck (Reefer)"
    if weight > 10000 or "construction" in cargo_lower:
        return "Freight Train (BCN Wagon)" if strategy == "cheap" else "Heavy Truck (18-Wheeler)"
    if strategy == "fast":
        return "Cargo Plane (Express)"
    return "Medium Truck (Eicher)"

def process_shipment(data: ShipmentRequest, order: int = None, existing_id: str = None):
    c1, c2 = STATE_COORDS.get(data.start, STATE_COORDS["Delhi"]), STATE_COORDS.get(data.destination, STATE_COORDS["Karnataka"])
    v_stats = VEHICLES.get(data.vehicle, VEHICLES["Medium Truck (Eicher)"])
    distance = calculate_distance(c1[0], c1[1], c2[0], c2[1])
    
    t_score = {"Clear": 2.0, "Moderate": 5.0, "Heavy": 9.0}.get(data.traffic, 2.0)
    w_score = {"Sunny": 0.1, "Hot": 0.2, "Rainy": 0.5, "Cold": 0.5, "Stormy": 0.9, "Extremely Hot": 0.9, "Extremely Cold": 0.9}.get(data.weather, 0.1)
    
    risk_base = 3.0 + (w_score * 3) + (t_score * 0.2)
    ml_risk = risk_base * 10
    
    ai_payload = pd.DataFrame([{ 
        'traffic_congestion_level': t_score, 'weather_condition_severity': w_score, 
        'route_risk_level': risk_base, 'driver_behavior_score': random.uniform(0.7, 1.0), 
        'disruption_likelihood_score': 0.9 if data.breakdown_sim != "None" else 0.1, 
        'Assigned_Payload_kg': data.weight, 'Base_Speed_kmph': v_stats["speed"], 
        'Volumetric_Factor': v_stats["vol"], 'Transport_Mode': v_stats["mode"], 
        'Speed_Category': v_stats["cat"] 
    }])
    
    eta_v = 0; cost_v = 0
    if 'eta_variation_hours' in models: 
        try: eta_v = models['eta_variation_hours'].predict(ai_payload)[0]
        except: pass
    if 'Dynamic_Shipping_Cost' in models: 
        try: cost_v = models['Dynamic_Shipping_Cost'].predict(ai_payload)[0]
        except: pass

    c_mult = 1.8 if "Pharmaceuticals" in data.cargo_class else 2.5 if "Vehicles" in data.cargo_class else 1.3 if "Perishables" in data.cargo_class else 1.0
    final_cost = ((distance * data.weight * v_stats["rate"] * c_mult) / 10) + (cost_v * 0.05) + 15000

    ideal_eta = distance / max(v_stats["speed"], 1); base_eta = ideal_eta
    if data.traffic == "Heavy": base_eta *= 1.5
    if w_score >= 0.5: base_eta *= 1.2
    
    final_eta = max(base_eta + eta_v, 1)
    env_delay_hours = final_eta - ideal_eta

    breakdown_info = None; delay_add = 0
    if data.breakdown_sim == "Minor": 
        delay_add = 4
        breakdown_info = {"type": "Minor Engine Fault", "action": "Mechanic Dispatched.", "delay": "+4.0h", "fee": "₹ 12,500"}
    elif data.breakdown_sim == "Major": 
        delay_add = 24
        breakdown_info = {"type": "Major Asset Failure", "action": "Emergency Transloading.", "delay": "+24.0h", "fee": "₹ 85,000"}
    elif data.breakdown_sim == "Theft": 
        final_eta = 999
        breakdown_info = {"type": "Security Breach", "action": "Signal Lost.", "delay": "Indefinite", "fee": "INSURANCE CLAIM"}
    elif env_delay_hours > 2.0 and (data.weather not in ["Sunny", "Clear"] or data.traffic != "Clear"):
        delay_add = env_delay_hours 
        reasons = []
        if data.weather not in ["Sunny", "Clear"]: reasons.append(f"{data.weather} weather")
        if data.traffic == "Heavy": reasons.append("heavy traffic")
        breakdown_info = {"type": "Environmental Delay", "action": f"Slowed due to {' and '.join(reasons)}.", "delay": f"+{round(env_delay_hours, 1)}h", "fee": "₹ 0"}

    ideal_temp = CARGO_IDEAL_TEMPS.get(data.cargo_class)
    ambient_temp = WEATHER_AMBIENT_TEMPS.get(data.weather, 25)
    set_temp = ideal_temp if ideal_temp is not None else ambient_temp
    if data.target_temp is not None: set_temp = data.target_temp

    now = datetime.now()
    return {
        "id": existing_id if existing_id else f"ML-{now.strftime('%H%M')}-{random.randint(1000,9999)}", 
        "origin": data.start, "destination": data.destination, "vehicle": data.vehicle,
        "cargo_class": data.cargo_class, "cost": "N/A" if data.breakdown_sim == "Theft" else f"₹ {int(final_cost):,}", 
        "eta": f"{round(final_eta + delay_add, 1)} Hours", "status": "Awaiting Loading", "breakdown": breakdown_info,
        "coords": [c1, c2], "dispatch_order": order,
        "ml_telemetry": {"risk_classification": "High" if ml_risk > 70 else "Medium" if ml_risk > 40 else "Low", "route_risk_level": round(ml_risk, 1), "iot_temperature": float(set_temp)},
        "ship_iso": None, "delivery_iso": None, "eta_hours_raw": round(final_eta + delay_add, 2), "handling": data.handling, "strategy": "Standard",
        "sim_state": {"weather": data.weather, "traffic": data.traffic, "breakdown_sim": data.breakdown_sim, "weight": data.weight}
    }

def get_handling_tags(s):
    html = ""
    cargo = s.get("cargo_class", "")
    temp = s.get("ml_telemetry", {}).get("iot_temperature", 25)
    
    if cargo in ["Electronics", "High-Value Goods", "Live Animals"]: 
        html += f"""<span class="px-2 py-1 bg-yellow-500/20 text-yellow-500 border border-yellow-500/40 rounded text-[9px] font-black uppercase mr-2 inline-block"><i class="fas fa-wine-glass mr-1"></i> Fragile</span>"""
    if "Chemicals" in cargo: 
        html += f"""<span class="px-2 py-1 bg-rose-500/20 text-rose-400 border border-rose-500/40 rounded text-[9px] font-black uppercase mr-2 inline-block animate-pulse"><i class="fas fa-biohazard mr-1"></i> HAZMAT</span>"""
    if temp < 15 or cargo in ["Pharmaceuticals", "Perishables"]: 
        html += f"""<span class="px-2 py-1 bg-blue-500/20 text-blue-400 border border-blue-500/40 rounded text-[9px] font-black uppercase mr-2 inline-block"><i class="fas fa-snowflake mr-1"></i> Cold Chain</span>"""
    
    if not html: 
        html = '<span class="text-slate-600 text-[9px] font-bold uppercase tracking-widest border border-slate-700/50 px-2 py-1 rounded inline-block">Standard Handling</span>'
    return html

def gen_monitor_html(s):
    if s['status'] == 'Awaiting Loading':
        action_ui = f'<button onclick="loadAgent(\'{s["id"]}\')" class="mt-6 w-full bg-blue-600 hover:bg-blue-500 py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all active:scale-95"><i class="fas fa-truck-loading mr-2"></i>Load Asset</button>'
    else:
        action_ui = f'<div class="mt-6 border-t border-slate-800 pt-6 flex justify-between"><div><p class="text-slate-500 font-black text-[10px]">ETA</p><p class="text-2xl font-black text-white">{s["eta"]}</p></div><div><p class="text-slate-500 font-black text-[10px]">COST</p><p class="text-2xl font-black text-white">{s["cost"]}</p></div></div>'

    return f"""<div class="bg-[#161b2b] rounded-[3rem] p-10 border border-blue-500/50 shadow-2xl relative overflow-hidden"><div class="absolute top-0 left-0 h-2 w-full bg-blue-500"></div><div class="text-blue-500 font-mono text-sm font-bold tracking-widest">{s['id']} <span class="ml-2 px-2 py-0.5 bg-blue-500/20 rounded text-[9px] uppercase">{s.get('strategy', 'Standard')}</span></div><h2 class="text-3xl font-black text-white mt-5 uppercase italic">{s['origin']} ➔ {s['destination']}</h2><p class="text-slate-400 font-bold text-xs mt-1 mb-3"><i class="fas fa-box-open mr-1"></i> {s['cargo_class']}</p><div>{get_handling_tags(s)}</div><div class="mt-8"><p class="text-slate-500 uppercase font-black text-[10px]">Status</p><span class="text-xl font-black text-blue-400 uppercase">{s['status']}</span></div>{action_ui}</div>"""

def gen_table_row(s):
    if s['status'] == 'Awaiting Loading':
        status_ui = f'<button onclick="loadAgent(\'{s["id"]}\')" class="bg-blue-600/20 text-blue-400 border border-blue-500/30 hover:bg-blue-600 hover:text-white px-4 py-2 rounded-xl font-black uppercase text-[10px] tracking-widest transition-all active:scale-95 shadow-lg"><i class="fas fa-truck-loading mr-2"></i> Load</button>'
        progress_html = ""
    else:
        status_ui = f'<span class="text-blue-400">{s["status"]}</span>'
        progress_html = f"""<div class="w-full bg-slate-800 rounded-full h-1.5 mt-3"><div class="progress-bar bg-blue-500 h-full rounded-full transition-all duration-1000" style="width: 0%" data-start="{s.get('ship_iso','')}" data-end="{s.get('delivery_iso','')}"></div></div><div class="live-clock text-[9px] font-mono text-blue-400 mt-1 text-right" data-target-time="{s.get('delivery_iso','')}" data-status="{s['status']}">Calculating...</div>""" if s.get('ship_iso') else ""
    
    return f"""<tr class="border-b border-slate-800/50 hover:bg-slate-800/20 transition"><td class="px-8 py-6 text-blue-500 font-mono font-black">{s['id']}</td><td class="px-8 py-6 text-white font-bold">{s['origin']} ➔ {s['destination']}<div class="text-xs text-slate-500 mt-1 mb-2">{s['cargo_class']} | {s['vehicle']}</div><div class="flex flex-wrap">{get_handling_tags(s)}</div></td><td class="px-8 py-6 w-56"><div class="text-emerald-400 font-black">{s['cost']}</div>{progress_html}</td><td class="px-8 py-6 text-center uppercase font-black text-xs">{status_ui}</td></tr>"""

def gen_sim_panel(s):
    if not s: return f"""<div class="flex flex-col items-center justify-center h-full text-slate-600 p-10"><i class="fas fa-satellite-dish text-6xl mb-4 opacity-50"></i><p class="font-black uppercase tracking-widest">Select an active dispatch to begin simulation</p></div>"""
    is_broken = s.get("breakdown") is not None; is_theft = is_broken and "Security" in s["breakdown"]["type"]
    b_color = 'purple' if is_theft else ('rose' if is_broken else 'blue')
    w_opts = "".join([f"<option value='{w}' {'selected' if s.get('sim_state',{}).get('weather')==w else ''}>{w}</option>" for w in WEATHER_AMBIENT_TEMPS.keys()])
    t_opts = "".join([f"<option value='{t}' {'selected' if s.get('sim_state',{}).get('traffic')==t else ''}>{t}</option>" for t in ["Clear", "Moderate", "Heavy"]])
    b_opts = "".join([f"<option value='{b}' {'selected' if s.get('sim_state',{}).get('breakdown_sim')==b else ''}>{b}</option>" for b in ["None", "Minor", "Major", "Theft"]])
    incident_html = f"""<div class="mt-6 p-4 border border-{b_color}-500/30 bg-{b_color}-950/20 rounded-2xl"><h4 class="text-{b_color}-400 font-black uppercase text-[10px] mb-1">INCIDENT REPORT: {s['breakdown']['type']}</h4><p class="text-slate-300 text-sm">{s['breakdown']['action']}</p><p class="text-{b_color}-400 font-mono font-bold text-xs mt-2">Added Delay: {s['breakdown']['delay']}</p></div>""" if s.get("breakdown") else ""
    return f"""<div class="bg-[#161b2b] rounded-[2.5rem] p-8 border border-{b_color}-500/50 shadow-2xl relative overflow-hidden"><div class="absolute top-0 left-0 h-2 w-full bg-{b_color}-500"></div><div class="flex justify-between items-start mb-6"><div><span class="text-{b_color}-500 font-mono text-sm font-bold tracking-widest bg-{b_color}-500/10 px-3 py-1 rounded-full">{s['id']}</span><h2 class="text-3xl font-black text-white mt-3 uppercase italic tracking-tighter truncate">{s['origin']} ➔ {s['destination']}</h2><div class="mt-2">{get_handling_tags(s)}</div></div><div class="text-right"><p class="text-[10px] text-slate-500 uppercase font-black tracking-widest mb-1">Live Status</p><span class="text-xl font-black uppercase tracking-widest block text-{b_color}-400">{s['status']}</span></div></div><div class="bg-slate-900/80 rounded-2xl p-5 border border-slate-700/50 text-center mb-8 flex flex-col justify-center"><p class="text-[10px] text-slate-500 uppercase font-black tracking-widest mb-2">Time travel Target</p><span class="live-clock text-5xl font-mono font-black text-{b_color}-400 block tracking-tighter" data-target-time="{s['delivery_iso']}" data-status="{s['status']}" data-color="blue">00:00:00</span><div class="w-full bg-slate-800 rounded-full h-2 mt-4"><div class="progress-bar bg-{b_color}-500 h-full rounded-full transition-all duration-1000" style="width: 0%" data-start="{s['ship_iso']}" data-end="{s['delivery_iso']}"></div></div></div><div class="grid grid-cols-4 gap-3 mb-8"><button type="button" onclick="event.preventDefault(); simTimeSkip('start')" class="bg-slate-800 hover:bg-blue-600 border border-slate-700 text-white font-black uppercase text-[9px] tracking-widest py-3 rounded-xl transition-all"><i class="fas fa-undo mb-1 text-lg block"></i> DISPATCH</button><button type="button" onclick="event.preventDefault(); simTimeSkip('half')" class="bg-slate-800 hover:bg-blue-600 border border-slate-700 text-white font-black uppercase text-[9px] tracking-widest py-3 rounded-xl transition-all"><i class="fas fa-forward-step mb-1 text-lg block"></i> HALF ROUTE</button><button type="button" onclick="event.preventDefault(); simTimeSkip('hub')" class="bg-slate-800 hover:bg-blue-600 border border-slate-700 text-white font-black uppercase text-[9px] tracking-widest py-3 rounded-xl transition-all"><i class="fas fa-warehouse mb-1 text-lg block"></i> STATE HUB</button><button type="button" onclick="event.preventDefault(); simTimeSkip('deliver')" class="bg-slate-800 hover:bg-emerald-600 border border-slate-700 text-white font-black uppercase text-[9px] tracking-widest py-3 rounded-xl transition-all"><i class="fas fa-check-double mb-1 text-lg block"></i> DELIVERED</button></div><div class="border-t border-slate-800 pt-6"><h4 class="text-[10px] text-blue-400 uppercase font-black tracking-widest mb-4"><i class="fas fa-bolt mr-1"></i> Agentic AI Mid-Route Injection</h4><div class="grid grid-cols-3 gap-4 mb-4"><select id="simWeather" class="bg-[#0b0f1a] border border-slate-700 rounded-lg p-2 text-xs text-white outline-none">{w_opts}</select><select id="simTraffic" class="bg-[#0b0f1a] border border-slate-700 rounded-lg p-2 text-xs text-white outline-none">{t_opts}</select><select id="simBreakdown" class="bg-rose-950/30 border border-rose-900 rounded-lg p-2 text-xs text-rose-300 outline-none">{b_opts}</select></div><button type="button" onclick="event.preventDefault(); simInjectEvent()" class="w-full bg-blue-600 text-white py-3 rounded-xl font-black uppercase text-[10px] tracking-[0.1em] transition-all shadow-lg hover:bg-blue-500 active:scale-95">Recalculate AI Physics</button></div>{incident_html}</div>"""

@app.post("/ui-state")
async def get_ui_state(req: UIStateRequest = None):
    req = req or UIStateRequest()
    history = rw_history("r"); history_rev = list(reversed(history))
    monitors = "".join([gen_monitor_html(s) for s in history_rev[:2]])
    table = "".join([gen_table_row(s) for s in history_rev])
    
    map_data = []; sim_list_html = ""; active_sim_obj = None; now = datetime.now().timestamp() * 1000
    for s in history_rev:
        if s['status'] not in ['Awaiting Loading', 'CANCELLED']:
            if req.active_sim_id and s['id'] == req.active_sim_id: active_sim_obj = s
            is_sel = (req.active_sim_id == s['id'])
            bg_sel = "bg-blue-900/40 border-blue-500 shadow-lg" if is_sel else "bg-slate-800/40 border-slate-700"
            sim_list_html += f"""<div onclick="selectSim('{s['id']}')" class="cursor-pointer p-4 rounded-xl border {bg_sel} transition-all mb-3"><div class="flex justify-between items-center mb-1"><span class="text-xs font-mono font-bold text-blue-400">{s['id']}</span></div><p class="text-sm font-bold text-white truncate">{s['origin']} ➔ {s['destination']}</p></div>"""
            
            d_order = s.get('dispatch_order') or 1
            color = '#475569' if s['status'] == 'DELIVERED' else QUEUE_COLORS[(d_order - 1) % len(QUEUE_COLORS)]
            progress = -1
            if s['ship_iso'] and s['delivery_iso']:
                s_ms = datetime.fromisoformat(s['ship_iso']).timestamp() * 1000; e_ms = datetime.fromisoformat(s['delivery_iso']).timestamp() * 1000
                if now >= e_ms: progress = 100
                elif now <= s_ms: progress = 0
                else: progress = ((now - s_ms) / (e_ms - s_ms)) * 100
            m_item = {"id": s['id'], "coords": s["coords"], "color": color, "dash": '5, 10', "weight": 5 if is_sel else 3, "popup": f"<b>{s['id']}</b><br>{s['destination']}", "progress": progress, "status": s['status']}
            if s.get("breakdown") and s["status"] != 'DELIVERED':
                mid_lat = (s["coords"][0][0] + s["coords"][1][0]) / 2; mid_lng = (s["coords"][0][1] + s["coords"][1][1]) / 2
                is_theft = "Security" in s["breakdown"]["type"]
                m_item["alert"] = { "coords": [mid_lat, mid_lng], "color": '#a855f7' if is_theft else '#f43f5e', "class": 'theft-marker' if is_theft else 'alert-marker', "popup": f"<b>{'SECURITY BREACH' if is_theft else 'CRITICAL FAILURE'}</b>" }
                m_item["color"] = m_item["alert"]["color"]; m_item["weight"] = 5
            map_data.append(m_item)
            
    return {"table_html": table, "monitors_html": monitors, "queue_count": len(PENDING_QUEUE), "queue_html": "", "map_data": map_data, "sim_list_html": sim_list_html, "sim_panel_html": gen_sim_panel(active_sim_obj)}

# --- SIMULATOR ROUTES ---
@app.post("/simulator/time-skip/{ship_id}")
async def time_skip(ship_id: str, data: dict):
    action = data.get("action"); h = rw_history("r")
    for s in h:
        if s["id"] == ship_id:
            now = datetime.now(); raw_eta = s["eta_hours_raw"]
            if action == "start": s["ship_iso"] = now.isoformat(); s["delivery_iso"] = (now + timedelta(hours=raw_eta)).isoformat(); s["status"] = "In Transit"
            elif action == "half": s["ship_iso"] = (now - timedelta(hours=raw_eta/2)).isoformat(); s["delivery_iso"] = (now + timedelta(hours=raw_eta/2)).isoformat(); s["status"] = "In Transit"
            elif action == "hub": elapsed = raw_eta * 0.9; remain = raw_eta * 0.1; s["ship_iso"] = (now - timedelta(hours=elapsed)).isoformat(); s["delivery_iso"] = (now + timedelta(hours=remain)).isoformat(); s["status"] = "At State Hub"
            elif action == "deliver": s["ship_iso"] = (now - timedelta(hours=raw_eta)).isoformat(); s["delivery_iso"] = (now - timedelta(minutes=1)).isoformat(); s["status"] = "DELIVERED"; s["breakdown"] = None
            rw_history("w", h); return s
    raise HTTPException(404, "Not found")

@app.post("/simulator/inject/{ship_id}")
async def inject_environment(ship_id: str, data: dict):
    h = rw_history("r")
    for i, s in enumerate(h):
        if s["id"] == ship_id:
            orig_start = s.get("ship_iso"); orig_eta = s.get("eta_hours_raw", 0); orig_delivery = s.get("delivery_iso")
            req = ShipmentRequest(start=s["origin"], destination=s["destination"], vehicle=s["vehicle"], weight=s.get("sim_state", {}).get("weight", 500), cargo_class=s["cargo_class"], customer_address=s.get("customer_address", "N/A"), target_temp=s["ml_telemetry"]["iot_temperature"], handling=s["handling"], traffic=data.get("traffic", "Clear"), weather=data.get("weather", "Sunny"), breakdown_sim=data.get("breakdown", "None"))
            new_s = process_shipment(req, s.get("dispatch_order"), existing_id=s["id"])
            time_diff_hours = new_s["eta_hours_raw"] - orig_eta
            if orig_start and orig_delivery:
                new_s["ship_iso"] = orig_start
                new_s["delivery_iso"] = (datetime.fromisoformat(orig_delivery) + timedelta(hours=time_diff_hours)).isoformat()
                if new_s["breakdown"]: t = new_s["breakdown"]["type"]; new_s["status"] = "CARGO STOLEN" if "Security" in t else "CRITICAL FAILURE" if "Major" in t else "DELAYED"
                else: new_s["status"] = "In Transit" if s["status"] in ["DELAYED", "CRITICAL FAILURE"] else s["status"]
            h[i] = new_s; rw_history("w", h); return new_s
    raise HTTPException(404, "Not found")

# --- 🌟 RESTORED TRACKING API FOR YOUR UI ---
@app.get("/track/{ship_id}")
async def track_shipment(ship_id: str):
    h = rw_history("r")
    for s in h:
        if s["id"].upper() == ship_id.upper():
            now = datetime.now().timestamp() * 1000
            progress = 0
            if s.get('ship_iso') and s.get('delivery_iso'):
                s_ms = datetime.fromisoformat(s['ship_iso']).timestamp() * 1000
                e_ms = datetime.fromisoformat(s['delivery_iso']).timestamp() * 1000
                if now >= e_ms: progress = 100
                elif now <= s_ms: progress = 0
                else: progress = ((now - s_ms) / (e_ms - s_ms)) * 100
            s['progress'] = progress
            return s
    raise HTTPException(404, "Not found")

# --- SMART COMMAND BOT (OFFLINE) ---
@app.post("/ai-agent")
async def ai_agent(data: AICommandRequest):
    msg = data.prompt.lower()
    global agent_sessions
    if agent_sessions.get("pending_options"):
        selected = None
        if "1" in msg or "first" in msg or "fast" in msg or "air" in msg: selected = 0
        elif "2" in msg or "second" in msg or "economy" in msg or "truck" in msg: selected = 1
        elif "3" in msg or "third" in msg or "bulk" in msg or "train" in msg: selected = 2
        if selected is not None and selected < len(agent_sessions["pending_options"]):
            opt = agent_sessions["pending_options"][selected]; res = process_shipment(opt)
            now = datetime.now(); res["ship_iso"] = now.isoformat(); res["delivery_iso"] = (now + timedelta(hours=res["eta_hours_raw"])).isoformat(); res["status"] = "In Transit"
            h = rw_history("r"); h.append(res); rw_history("w", h); agent_sessions["pending_options"] = None
            return {"status": "success", "message": f"Excellent choice! I've booked the {opt.vehicle}. The shipment is already loaded and **In Transit**. Estimated ETA: {res['eta']}. Cost: {res['cost']}.", "action": "dispatch"}
        elif "cancel" in msg or "nevermind" in msg:
            agent_sessions["pending_options"] = None
            return {"status": "success", "message": "Options cleared. What else can I help you with?", "action": "chat"}

    if "triage" in msg or "optimize" in msg:
        h = rw_history("r"); pending = [s for s in h if s["status"] == "Awaiting Loading"]
        if not pending: return {"status": "success", "message": "There are no pending shipments in the queue to triage.", "action": "none"}
        pending.sort(key=lambda x: x["ml_telemetry"]["route_risk_level"])
        for i, s in enumerate(pending): s["dispatch_order"] = i + 1
        for s in h:
            for p in pending:
                if s["id"] == p["id"]: s.update(p)
        rw_history("w", h)
        return {"status": "success", "message": f"Done! I've optimized and triaged {len(pending)} shipments based on ML risk scores.", "action": "dispatch"}

    if "cancel all" in msg or "purge" in msg:
        h = rw_history("r"); count = 0
        for s in h:
            if s["status"] == "Awaiting Loading": s["status"] = "CANCELLED"; count += 1
        rw_history("w", h)
        return {"status": "success", "message": f"I've cancelled {count} shipments that were awaiting dispatch.", "action": "dispatch"}

    if any(x in msg for x in ["send", "ship", "dispatch", "book", "deliver", "transport"]):
        start = "Delhi"; dest = "Maharashtra"
        for state in STATE_COORDS.keys():
            if state.lower() in msg:
                if "from " + state.lower() in msg: start = state
                else: dest = state
        weight = 1500.0
        weight_match = re.search(r'(\d+(?:\.\d+)?)\s*(kg|kilos|tons|ton)', msg)
        if weight_match:
            val = float(weight_match.group(1))
            if 'ton' in weight_match.group(2): val *= 1000
            weight = val
        cargo = "General Objects"
        if "pharma" in msg or "medical" in msg: cargo = "Pharmaceuticals"
        elif "food" in msg or "perishable" in msg: cargo = "Perishables"
        elif "electronic" in msg: cargo = "Electronics"
        elif "chemical" in msg or "acid" in msg: cargo = "Chemicals: Sulfuric Acid"

        options = []
        v_air = "Cargo Plane (Express)" if weight <= 5000 else "Heavy Cargo Aircraft (HCA)"
        options.append(ShipmentRequest(start=start, destination=dest, vehicle=v_air, weight=weight, cargo_class=cargo, traffic="Clear", weather="Sunny", breakdown_sim="None"))
        v_road = "Medium Truck (Eicher)"
        if cargo in ["Pharmaceuticals", "Perishables"]: v_road = "Refrigerated Truck (Reefer)"
        elif weight <= 1500: v_road = "Mini Truck (Tata Ace)"
        elif weight <= 8000: v_road = "Medium Truck (Eicher)"
        elif weight <= 35000: v_road = "Heavy Truck (18-Wheeler)"
        else: v_road = "Hydraulic Trailer (ODC)"
        options.append(ShipmentRequest(start=start, destination=dest, vehicle=v_road, weight=weight, cargo_class=cargo, traffic="Clear", weather="Sunny", breakdown_sim="None"))
        if cargo == "Chemicals: Sulfuric Acid": options.append(ShipmentRequest(start=start, destination=dest, vehicle="Freight Train (BTPN Tank)", weight=weight, cargo_class=cargo, traffic="Clear", weather="Sunny", breakdown_sim="None"))
        elif weight > 5000: options.append(ShipmentRequest(start=start, destination=dest, vehicle="Freight Train (BCN Wagon)", weight=weight, cargo_class=cargo, traffic="Clear", weather="Sunny", breakdown_sim="None"))
        else:
             if v_road != "Mini Truck (Tata Ace)": options.append(ShipmentRequest(start=start, destination=dest, vehicle="Mini Truck (Tata Ace)", weight=weight, cargo_class=cargo, traffic="Clear", weather="Sunny", breakdown_sim="None"))

        options = options[:3]; agent_sessions["pending_options"] = options
        response_text = f"I can arrange the shipment of {weight}kg of {cargo} from {start} to {dest}. Here are your options:<br><br>"
        labels = ["Fast Priority", "Economy", "Bulk / Alt"]
        for i, opt in enumerate(options):
            res = process_shipment(opt)
            response_text += f"<b>Option {i+1} ({labels[i]}):</b> {opt.vehicle}<br><b>ETA:</b> {res['eta']} &nbsp;|&nbsp; <b>Cost:</b> {res['cost']}<br><br>"
        opts_str = ", ".join([f"'{i+1}'" for i in range(1, len(options)+1)])
        response_text += f"Reply with {opts_str} to select and launch."
        return {"status": "success", "message": response_text, "action": "chat"}

    if "status" in msg or "active" in msg:
        h = rw_history("r"); active = [s for s in h if s["status"] not in ["DELIVERED", "CANCELLED"]]
        stolen = len([s for s in active if s["status"] == "CARGO STOLEN"]); failed = len([s for s in active if s["status"] == "CRITICAL FAILURE"])
        rep = f"You have {len(active)} active shipments in the network."
        if stolen > 0: rep += f"<br><span class='text-rose-400'>ALERT: {stolen} shipments have been stolen!</span>"
        if failed > 0: rep += f"<br><span class='text-rose-400'>WARNING: {failed} shipments are halted due to failure.</span>"
        return {"status": "success", "message": rep, "action": "chat"}
        
    risk_match = re.search(r"risk report for ([\w-]+)", msg, re.IGNORECASE)
    if risk_match:
        h = rw_history("r"); ship_id = risk_match.group(1).upper()
        if ship_id == "LATEST" and len(h) > 0: target = h[-1]
        else: target = next((s for s in h if s['id'] == ship_id), None)
        if target: return {"status": "success", "message": f"Security Audit {target['id']}: Risk level is {target['ml_telemetry']['route_risk_level']}/100. Status: Secure.", "action": "chat"}
        return {"status": "error", "message": "ML-ID not found. Please dispatch a shipment first.", "action": "error"}

    return {"status": "error", "message": "Command not recognized. Try 'dispatch 1500kg pharma from Assam to Delhi', 'triage', 'status', or 'risk report for LATEST'.", "action": "error"}

@app.post("/action/load/{ship_id}")
async def load_shipment(ship_id: str):
    h = rw_history("r")
    for s in h:
        if s["id"] == ship_id:
            s["status"] = "In Transit"
            now = datetime.now()
            s["ship_iso"] = now.isoformat()
            s["delivery_iso"] = (now + timedelta(hours=s["eta_hours_raw"])).isoformat()
            rw_history("w", h)
            return s
    raise HTTPException(404, "Not found")

@app.post("/queue/add")
async def add_queue(data: dict):
    global PENDING_QUEUE; PENDING_QUEUE.append(data); return {"queue_length": len(PENDING_QUEUE)}

@app.post("/queue/execute")
async def execute_queue(data: dict):
    global PENDING_QUEUE; h = rw_history("r"); final = []
    for i, req in enumerate(PENDING_QUEUE):
        s_req = ShipmentRequest(**req); s_res = process_shipment(s_req, i+1)
        s_res["status"] = "In Transit"; s_res["ship_iso"] = datetime.now().isoformat(); s_res["delivery_iso"] = (datetime.now() + timedelta(hours=s_res["eta_hours_raw"])).isoformat(); final.append(s_res)
    h.extend(final); rw_history("w", h); PENDING_QUEUE.clear(); return final

@app.post("/action/auto-fleet")
async def auto_fleet(data: dict):
    start = data.get("start"); dest = data.get("destination"); product = data.get("cargo_class"); weight = float(data.get("weight", 500))
    fast_veh = suggest_vehicle(product, weight, "fast")
    fast_ship = process_shipment(ShipmentRequest(start=start, destination=dest, vehicle=fast_veh, weight=weight, cargo_class=product, traffic="Clear", weather="Sunny"), order=1)
    fast_ship["strategy"] = "Alpha (Fastest Route)"; fast_ship["id"] = f"FAST-{random.randint(100,999)}"
    safe_veh = suggest_vehicle(product, weight, "cheap")
    slow_ship = process_shipment(ShipmentRequest(start=start, destination=dest, vehicle=safe_veh, weight=weight, cargo_class=product, traffic="Moderate", weather="Sunny"), order=2)
    slow_ship["strategy"] = "Gamma (Economy & Safe)"; slow_ship["id"] = f"ECON-{random.randint(100,999)}"
    PROPOSAL_DB["current"] = [fast_ship, slow_ship]
    return {"status": "proposals_generated", "proposals": [fast_ship, slow_ship]}

@app.post("/action/confirm-proposal/{ship_id}")
async def confirm_proposal(ship_id: str):
    h = rw_history("r"); props = PROPOSAL_DB.get("current", [])
    for p in props:
        if p["id"] == ship_id:
            p["status"] = "In Transit"; p["ship_iso"] = datetime.now().isoformat(); p["delivery_iso"] = (datetime.now() + timedelta(hours=p["eta_hours_raw"])).isoformat()
            h.append(p); rw_history("w", h); PROPOSAL_DB["current"] = [] 
            return p
    raise HTTPException(404, "Proposal not found")

@app.get("/config")
async def get_config(): return {"states": sorted(list(STATE_COORDS.keys())), "cargo_classes": list(CARGO_IDEAL_TEMPS.keys()), "weather_options": list(WEATHER_AMBIENT_TEMPS.keys()), "traffic_options": ["Clear", "Moderate", "Heavy"], "breakdown_options": ["None", "Minor", "Major", "Theft"], "vehicles": list(VEHICLES.keys())}
@app.post("/get-distance")
async def get_dist(data: dict): return {"distance": calculate_distance(STATE_COORDS[data['start']][0], STATE_COORDS[data['start']][1], STATE_COORDS[data['destination']][0], STATE_COORDS[data['destination']][1])}
@app.post("/calc-temp")
async def calc_temp(data: dict): return {"target_temp": CARGO_IDEAL_TEMPS.get(data.get("cargo_class")) or 22.0, "status_type": "eco", "ambient": 25}

@app.post("/create-shipment")
async def create(data: ShipmentRequest):
    res = process_shipment(data)
    h = rw_history("r"); h.append(res); rw_history("w", h)
    return res

@app.delete("/clear-history")
async def clear_history():
    if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
    global PENDING_QUEUE, PROPOSAL_DB, agent_sessions
    PENDING_QUEUE.clear(); PROPOSAL_DB.clear(); agent_sessions["pending_options"] = None
    return {"status": "ok"}