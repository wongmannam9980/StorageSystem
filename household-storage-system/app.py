import os
import shutil
import cv2 # pyright: ignore[reportMissingImports]
import serial # pyright: ignore[reportMissingImports]
import serial.tools.list_ports # pyright: ignore[reportMissingImports]
from datetime import datetime
import rfid_serial as rs
import time
import json
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)
ser = None

# Configuration
DATA_FILE = 'storage_data.json'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'images')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- JSON PERSISTENCE HELPERS ---

def load_data():
    """Load bins and logs from the JSON file."""
    if not os.path.exists(DATA_FILE):
        return {
            "bins": [
                {"id": 1, "label": "Bin 1", "item": None, "quantity": 0, "image": None, "status": "empty", "physical_state": "waiting", "rfid_record": [], "mode": "manual", "tracking_id": None},
                {"id": 2, "label": "Bin 2", "item": None, "quantity": 0, "image": None, "status": "empty", "physical_state": "waiting", "rfid_record": [], "mode": "manual", "tracking_id": None}
            ],
            "logs": []
        }
    with open(DATA_FILE, 'r') as f:
        data = json.load(f)
        for b in data.get("bins", []):
            b.setdefault("mode", "manual")
            b.setdefault("rfid_record", [])
            b.setdefault("tracking_id", None)
            b.setdefault("quantity", 0)
        return data

def save_data():
    """Save the current global state to the JSON file."""
    data_to_save = {
        "bins": storage_bins,
        "logs": system_records
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data_to_save, f, indent=4)

persisted_data = load_data()
storage_bins = persisted_data["bins"]
system_records = persisted_data["logs"]

#cv2 - Optimized for Macbook Camera
folder_name = "static/images/"
def get_next_filename(base_name="img", extension="jpg"):
    i = 1
    while os.path.exists(folder_name + f"{base_name}_{i}.{extension}"):
        i += 1
    return f"{base_name}_{i}.{extension}"

def take_photo():
    # Use AVFOUNDATION for Mac webcams specifically
    cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        # Fallback to default
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Could not access the webcam.")
            return None
            
    # CRITICAL FOR MAC: Give the camera sensor 1 second to turn on and adjust lighting
    time.sleep(1.0)
    
    # Read a few throwaway frames to clear buffer
    for _ in range(5):
        cap.read()
        
    ret, frame = cap.read()
    if ret:
        filename = get_next_filename()
        cv2.imwrite(folder_name + filename, frame)
        print(f"Photo saved as: {filename}")
    else:
        print("Error: Could not grab a frame.")
        filename = None
        
    cap.release()
    return filename

# --- APP LOGIC ---

def add_log(action_type, details):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_records.insert(0, {"time": timestamp, "action": action_type, "details": details})
    save_data()

@app.route("/")
def dashboard():
    stats = {
        "total": len(storage_bins), 
        "used": sum(1 for b in storage_bins if b["status"] == "occupied"), 
        "total_count": sum(b.get("quantity", 0) or 0 for b in storage_bins)
    }
    return render_template("dashboard.html", stats=stats, bins=storage_bins, logs=system_records)

@app.route("/storage")
def storage():
    return render_template("storage.html", bins=storage_bins, logs=system_records)

@app.route("/connection")
def connection():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return render_template("connection.html", ports=ports)

def send2serial(text):
    global ser
    if ser and ser.is_open:
        try:
            ser.write((text + '\n').encode('utf-8'))
            return jsonify({"status": "sent"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error", "message": "Connect to a port first!"}), 400

@app.route('/send', methods=['POST'])
def send_command():
    command = request.json.get('command')
    return send2serial(command)

@app.route('/connect', methods=['POST'])
def connect():
    global ser
    port = request.json.get('port')
    try:
        if ser and ser.is_open:
            ser.close()
        ser = serial.Serial(port, 9600, timeout=1)
        time.sleep(2) 
        send2serial("home_y")
        send2serial("home_z")
        return jsonify({"status": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/Master_reset', methods=['POST'])
def Master_reset():
    global storage_bins, system_records
    
    # Delete the physical files
    if os.path.exists('storage_data.json'):
        os.remove('storage_data.json')
    if os.path.exists('static/images'):
        shutil.rmtree('static/images')
        os.makedirs('static/images', exist_ok=True)
        
    # CLEAR IN-MEMORY VARIABLES IMMEDIATELY
    storage_bins = [
        {"id": 1, "label": "Bin 1", "item": None, "quantity": 0, "image": None, "status": "empty", "physical_state": "waiting", "rfid_record": [], "mode": "manual", "tracking_id": None},
        {"id": 2, "label": "Bin 2", "item": None, "quantity": 0, "image": None, "status": "empty", "physical_state": "waiting", "rfid_record": [], "mode": "manual", "tracking_id": None}
    ]
    system_records = []
    
    # Save this fresh empty state to a new JSON file
    save_data()
    
    return jsonify({"status": "reseted"})

@app.route("/initialize", methods=["POST"])
def initialize_system():
    global storage_bins, system_records
    storage_bins = [
        {"id": 1, "label": "Bin 1", "item": None, "quantity": 0, "image": None, "status": "empty", "physical_state": "waiting", "rfid_record": [], "mode": "manual", "tracking_id": None},
        {"id": 2, "label": "Bin 2", "item": None, "quantity": 0, "image": None, "status": "empty", "physical_state": "waiting", "rfid_record": [], "mode": "manual", "tracking_id": None}
    ]
    system_records = []
    add_log("System Reset", "All data cleared by Admin.")
    save_data()
    flash("System Initialized! All bins cleared.", "success")
    return redirect(url_for('storage'))

@app.route('/set_mode/<int:bin_id>', methods=['POST'])
def set_mode(bin_id):
    obj = next((b for b in storage_bins if b["id"] == bin_id), None)
    if obj:
        new_mode = request.form.get('mode')
        if new_mode in ['manual', 'rfid', 'camera']:
            obj["mode"] = new_mode
            save_data()
    return redirect(url_for('storage'))

@app.route('/call_next_empty', methods=['POST'])
def call_next_empty():
    empty_bin = next((b for b in storage_bins if b["status"] == "empty" and b["physical_state"] == "waiting"), None)
    if empty_bin:
        empty_bin["physical_state"] = "called_out"
        add_log("Called Out", f"{empty_bin['label']} requested by user.")
        flash(f"{empty_bin['label']} is on its way to the Station!", "success")
        send2serial(f'b{empty_bin["id"]}_2_L_n')
        save_data()
    else:
        flash("No empty bins available in the rack!", "warning")
    return redirect(url_for('storage'))

@app.route("/update_bin/<int:bin_id>", methods=["POST"])
def update_bin(bin_id):
    obj = next((b for b in storage_bins if b["id"] == bin_id), None)

    if obj:
        action = request.form.get("action")
        
        if action == "call_out":
            obj["physical_state"] = "called_out"
            msg = f"{obj['tracking_id']} accessed." if obj.get("tracking_id") else f"{obj['label']} accessed."
            flash(msg, "success")
            send2serial(f'b{bin_id}_2_L_n')
            
        elif action == "return_wait":
            obj["physical_state"] = "waiting"
            flash(f"{obj['label']} returned.", "success")
            send2serial(f'L_2_b{bin_id}_n')
            
        elif action == "storage" and obj["physical_state"] == "called_out":
            obj["status"] = "occupied"
            
            # AUTOMATIC ITEM NAMING IF EMPTY
            item_input = request.form.get("item_name", "").strip()
            if not item_input:
                item_input = f"Item #{secrets.token_hex(2).upper()}"
            obj["item"] = item_input
            
            obj["tracking_id"] = f"TRK-{secrets.token_hex(3).upper()}"
            
            current_mode = obj.get("mode", "manual")
            
            if current_mode == "manual":
                obj["quantity"] = max(1, int(request.form.get("amount") or 1))
                obj["image"] = take_photo()
                
            elif current_mode == "rfid":
                occupied_rfid = []
                for i in storage_bins:
                    for x in i['rfid_record']:
                        occupied_rfid.append(x)
                new_scan = [1234567,132413423,1242435]
                new_record = []
                for i in new_scan:
                    if not i in occupied_rfid:
                        new_record.append(i)
                obj["rfid_record"] = new_record
                obj["quantity"] = len(new_record)
                obj["image"] = take_photo()
                
            elif current_mode == "camera":
                obj["quantity"] = 0 # No quantity in camera mode
                obj["image"] = take_photo()
            
            qty_text = f"{obj['quantity']}x " if obj.get("quantity") else ""
            add_log("Item Stored", f"{qty_text}{obj['item']} stored under ID: {obj['tracking_id']}.")
            
        elif action == "delete":
            delete_qty = int(request.form.get("delete_qty", 0))
            
            if delete_qty > 0 and delete_qty <= obj["quantity"]:
                obj["quantity"] -= delete_qty
                item_name = obj["item"]
                
                # If quantity reaches 0, clear out the bin completely
                if obj["quantity"] <= 0:
                    trk_id = obj["tracking_id"]
                    obj.update({"status": "empty", "item": None, "quantity": 0, "image": None, "tracking_id": None})
                    add_log("Item Depleted", f"All {item_name} retrieved. {trk_id} cleared.")
                    flash(f"Success: All quantities of {item_name} have been retrieved.", "success")
                else:
                    add_log("Quantity Retrieved", f"{delete_qty}x {item_name} retrieved. {obj['quantity']} remaining.")
                    flash(f"Success: {delete_qty}x {item_name} retrieved.", "success")
            else:
                flash(f"Error: Invalid quantity entered.", "error")
                
        elif action == "clear_all":
            # Wipes out the bin regardless of the mode
            trk_id = obj.get("tracking_id", "Unknown ID")
            obj.update({"status": "empty", "item": None, "quantity": 0, "image": None, "tracking_id": None, "rfid_record": []})
            add_log("Bin Wiped", f"All data completely cleaned up in {obj['label']} ({trk_id}).")
            flash(f"Success: All data in {obj['label']} has been cleaned up.", "success")
        
        save_data()
                
    return redirect(request.referrer)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)