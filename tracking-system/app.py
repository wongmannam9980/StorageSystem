import os, secrets, smtplib, io, qrcode, base64, random, json
import cv2
from email.utils import make_msgid
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'images')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587
SENDER_EMAIL = "binflex2@gmail.com"
SENDER_PASSWORD = "sgmq dmrh dkgp prof"

def send_qr_email(recipient_email, item_name, qrcode_pin, locker_label, tracking_id):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qrcode_pin)
        img_buffer = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(img_buffer, format="PNG")
        img_buffer.seek(0)

        msg = MIMEMultipart('related')
        msg['From'] = SENDER_EMAIL
        msg['To'] = recipient_email
        msg['Subject'] = f"Smart Locker: Your Item is Stored [{tracking_id}]"
        msg['Message-ID'] = make_msgid()

        html_body = f"""
        <html><body style="font-family: Arial, sans-serif; text-align: center; background-color: #f3f4f6; padding: 20px;">
            <div style="max-width: 500px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px;">
                <h2 style="color: #2563eb;">📦 Item Stored Successfully!</h2>
                <p>Your item <strong>{item_name}</strong> has been securely stored.</p>
                <p style="font-size: 14px; color: #4b5563; background: #e5e7eb; padding: 8px; border-radius: 6px; display: inline-block;">
                    <strong>Tracking ID:</strong> {tracking_id}
                </p>
                <hr style="margin: 20px 0;">
                <p style="font-size: 14px; color: #6b7280;">📍 <strong>Location:</strong> {locker_label}</p>
                <p style="font-size: 14px; color: #6b7280;">Use the QR Code or PIN below to retrieve your item later:</p>
                <img src="cid:qr_image" alt="QR Code" style="width: 200px; height: 200px; margin: 20px 0; border: 1px solid #e5e7eb; border-radius: 8px;">
                <p style="color: #374151;">Or enter this PIN manually:</p>
                <h1 style="letter-spacing: 8px; background: #f9fafb; display: inline-block; padding: 12px 20px; border-radius: 8px; border: 2px dashed #2563eb; color: #2563eb;">{qrcode_pin}</h1>
            </div>
        </body></html>
        """
        msg.attach(MIMEText(html_body, 'html'))
        img_attachment = MIMEImage(img_buffer.read())
        img_attachment.add_header('Content-ID', '<qr_image>')
        msg.attach(img_attachment)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"EMAIL ERROR: {e}")
        return False

# ==========================================
# JSON LOAD / SAVE LOGIC
# ==========================================
JSON_FILE = 'system_state.json'
system_records = []
return_records = []

tracking_packages = [
    {"id": 1, "label": "Locker 1", "customer": None, "item": None, "quantity": 0, "status": "empty", "image": None, "qrcode": None, "physical_state": "waiting", "stored_time": None, "returned_time": None, "tracking_id": None},
    {"id": 2, "label": "Locker 2", "customer": None, "item": None, "quantity": 0, "status": "empty", "image": None, "qrcode": None, "physical_state": "waiting", "stored_time": None, "returned_time": None, "tracking_id": None}
]

# ==========================================
# LOAD DATA (RUNS ON STARTUP)
# ==========================================
if os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
            
            # 1. Load Packages & Fix Dates
            loaded_packages = data.get("packages", [])
            for p in loaded_packages:
                if p.get("stored_time"): p["stored_time"] = datetime.fromisoformat(p["stored_time"])
                if p.get("returned_time"): p["returned_time"] = datetime.fromisoformat(p["returned_time"])
            if loaded_packages:
                tracking_packages = loaded_packages
            
            # 2. Load Logs
            system_records = data.get("logs", [])
            
            # 3. Load Return Records
            return_records = data.get("returns", [])
            
    except Exception as e:
        print(f"⚠️ Could not load JSON data. Error: {e}")

# ==========================================
# SAVE DATA (CALLED WHENEVER DATA CHANGES)
# ==========================================
def save_state_to_json():
    # Prepare packages for JSON (Converting datetime to strings)
    safe_packages = []
    for p in tracking_packages:
        safe_p = p.copy()
        if safe_p.get("stored_time"): safe_p["stored_time"] = safe_p["stored_time"].isoformat()
        if safe_p.get("returned_time"): safe_p["returned_time"] = safe_p["returned_time"].isoformat()
        safe_packages.append(safe_p)

    # Combine into one dictionary
    full_state = {
        "packages": safe_packages,
        "logs": system_records[:100],  # Keep only the last 100 logs to keep file small
        "returns": return_records[:100] # Save return records too
    }

    with open(JSON_FILE, 'w') as f:
        json.dump(full_state, f, indent=4)

# ==========================================
# LOGGING FUNCTION
# ==========================================
def add_log(action, details):
    new_log = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
        "action": action, 
        "details": details
    }
    system_records.insert(0, new_log)
    save_state_to_json()

# ==========================================
# LIVE CAMERA LOGIC & OPENCV QR SCANNING
# ==========================================
latest_scanned_qr = None

def get_camera():
    """Tries index 0 first, then 1. Uses AVFOUNDATION for Mac compatibility."""
    cam = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    if not cam.isOpened() or not cam.read()[0]:
        cam.release()
        cam = cv2.VideoCapture(1, cv2.CAP_AVFOUNDATION)
    return cam

def generate_frames():
    global latest_scanned_qr
    cam = get_camera()
    qr_detector = cv2.QRCodeDetector()
    
    if not cam.isOpened():
        return
        
    while True:
        success, frame = cam.read()
        if not success:
            break
        else:
            # Detect and Decode QR Code
            data, bbox, _ = qr_detector.detectAndDecode(frame)
            
            if data:
                # Draw a green box around the QR code on the camera feed
                if bbox is not None:
                    bbox = bbox[0].astype(int)
                    for i in range(len(bbox)):
                        cv2.line(frame, tuple(bbox[i]), tuple(bbox[(i+1) % len(bbox)]), color=(0, 255, 0), thickness=3)
                
                # Save data globally so the frontend can fetch it
                if data != latest_scanned_qr:
                    latest_scanned_qr = data
                    
            # Stream the image out to the HTML
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    cam.release()

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/check_qr')
def check_qr():
    """Frontend pings this to see if OpenCV found a QR code."""
    global latest_scanned_qr
    if latest_scanned_qr:
        scanned_data = latest_scanned_qr
        latest_scanned_qr = None # Reset it immediately so it doesn't trigger a million times
        return jsonify({"found": True, "data": scanned_data})
    return jsonify({"found": False})

@app.route('/api/rfid_update', methods=['POST'])
def api_rfid_update():
    """Hardware hits this endpoint when RFID count updates"""
    data = request.json or {}
    bin_id = data.get('bin_id')
    rfid_count = data.get('rfid_count', 0)
    
    obj = next((b for b in tracking_packages if b['id'] == bin_id), None)
    
    # If the bin is currently out at the station for retrieval
    if obj and obj['physical_state'] == 'calledout' and obj['status'] == 'retrieving':
        if rfid_count == 0:
            add_log("Hardware Trigger", f"{obj['label']} detected 0 items. Automatically returning to rack.")
            
            # Wipe item and send back to rack
            obj.update({
                "status": "empty", 
                "customer": None, 
                "item": None, 
                "quantity": 0, 
                "qrcode": None, 
                "image": None, 
                "stored_time": None, 
                "tracking_id": None,
                "physical_state": "waiting", 
                "returned_time": datetime.now()
            })
            save_state_to_json()
            return jsonify({"status": "success", "message": "Bin emptied and returned"}), 200

    return jsonify({"status": "ignored", "message": "No action taken"}), 200

# ==========================================
# FLASK ROUTES
# ==========================================
@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/set_role/<role>')
def set_role(role):
    session['role'] = role
    if role == 'user':
        return redirect(url_for('storage'))
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'developer':
        return redirect(url_for('landing'))
    stats = {"total": len(tracking_packages), "used": sum(1 for b in tracking_packages if b['status'] == 'occupied')}
    return render_template('dashboard.html', role=session.get('role'), stats=stats, lockers=tracking_packages, logs=system_records)

@app.route('/hardware')
def hardware():
    if session.get('role') != 'developer': return redirect(url_for('landing'))
    return render_template('hardware.html')

@app.route('/storage')
def storage():
    role = session.get('role')
    if not role: return redirect(url_for('landing'))
    return render_template('storage.html', role=role, lockers=tracking_packages, now=datetime.now(), return_records=return_records)

@app.route('/setup_connection', methods=['POST'])
def setup_connection():
    if session.get('role') == 'developer':
        add_log("Hardware", "Serial connection established.")
        flash("Hardware successfully connected!", "success")
    return redirect(url_for('hardware'))

@app.route('/call_next_empty', methods=['POST'])
def call_next_empty():
    role = session.get('role')
    if role in ['developer', 'user']:
        empty_bin = next((b for b in tracking_packages if b['status'] == 'empty' and b['physical_state'] == 'waiting'), None)
        if empty_bin:
            empty_bin['physical_state'] = 'calledout'
            add_log("Called Out", f"{empty_bin['label']} called out automatically by {role.title()}.")
            flash(f"{empty_bin['label']} is on its way to the Station!", "success")
            save_state_to_json()
        else:
            flash("No empty bins available in the rack!", "warning")
    return redirect(url_for('storage'))

@app.route('/initialize', methods=['POST'])
def initialize_system():
    if session.get('role') == 'developer':
        for b in tracking_packages:
            b.update({"customer": None, "item": None, "quantity": 0, "status": "empty", "image": None, "qrcode": None, "physical_state": "waiting", "stored_time": None, "returned_time": None, "tracking_id": None})
        
        # Also clear the return records on reset
        return_records.clear()
        
        add_log("System Reset", "All data cleared by Admin.")
        flash("System Initialized! All lockers cleared.", "success")
        save_state_to_json()
    return redirect(request.referrer)

@app.route('/verify_global_pin', methods=['POST'])
def verify_global_pin():
    role = session.get('role')
    if role != 'user':
        return redirect(request.referrer)
        
    entered_pin = request.form.get('qrcode_input', '').upper().strip()
    
    matched_bin = next((b for b in tracking_packages if b['qrcode'] == entered_pin and b['status'] == 'occupied' and b['physical_state'] == 'waiting'), None)
    
    if matched_bin:
        # 1. Add to records BEFORE wiping data
        return_records.insert(0, {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label": matched_bin['label'],
            "item": matched_bin['item'] if matched_bin['item'] else "Unknown",
            "customer": matched_bin['customer'] if matched_bin['customer'] else "N/A"
        })
        
        add_log("Pickup", f"Customer retrieved {matched_bin['item']} from {matched_bin['label']}. Data cleared.")
        
        # 2. DELETE personal data, but KEEP item/image temporarily for the announcement
        matched_bin.update({
            "status": "retrieving",   
            "customer": None,       # PII deleted instantly
            "qrcode": None,         # PIN deleted instantly
            "tracking_id": None,    # Tracking deleted instantly
            "physical_state": "calledout",
            "returned_time": datetime.now()
        })
        
        flash(f"✅ PIN Verified! Locker is open.", "success")
        save_state_to_json()
    else:
        flash("❌ Invalid PIN Code. Please try again.", "danger")
        
    return redirect(request.referrer)

@app.route('/update_bin/<int:bin_id>', methods=['POST'])
def update_bin(bin_id):
    obj = next((b for b in tracking_packages if b['id'] == bin_id), None)
    role = session.get('role', 'developer')

    if obj:
        action = request.form.get('action')
        
        # --- Check if retrieval area is occupied ---
        if action in ['callout', 'user_scan']:
            occupied_bin = next((b for b in tracking_packages if b['physical_state'] == 'calledout'), None)
            
            if occupied_bin and occupied_bin['id'] != bin_id:
                flash(f"Retrieval area is currently occupied by {occupied_bin['label']}! Please wait.", "danger")
                return redirect(request.referrer)

        # Handle Image Uploads
        file = request.files.get('item_photo')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            obj['image'] = filename

        # --- CORE ACTIONS ---
        if action == 'callout':
            obj['physical_state'] = 'calledout'
            
        elif action == 'return_wait':
            obj['physical_state'] = 'waiting'

        # --- DEV ACTIONS ---
        elif role == 'developer' and obj['physical_state'] == 'calledout':
            if action == 'store_send_qr':
                obj['status'] = 'occupied'
                obj['customer'] = request.form.get('customer_name', 'No Email')
                obj['item'] = request.form.get('item_details', 'Unknown Item')
                obj['qrcode'] = secrets.token_hex(3).upper()
                obj['tracking_id'] = f"TRK-{secrets.token_hex(4).upper()}"
                obj['stored_time'] = datetime.now()
                
                add_log("Lodged", f"Stored {obj['item']} for {obj['customer']}.")

                # Only send email if a real email exists (Requires 5 arguments now)
                if '@' in obj['customer']:
                    success = send_qr_email(obj['customer'], obj['item'], obj['qrcode'], obj['label'], obj['tracking_id'])
                    if success:
                        flash(f"Stored & Email Sent to {obj['customer']}!", "success")
                    else:
                        flash("Stored, but Email Failed. Check console.", "warning")
                else:
                    flash(f"Stored! PIN: {obj['qrcode']}", "success")
                
                save_state_to_json()

            elif action == 'retrieve':
                obj['status'] = 'empty'
                obj['customer'] = None
                obj['item'] = None
                obj['qrcode'] = None
                obj['image'] = None
                obj['tracking_id'] = None
                flash("Locker forcefully cleared.", "success")
                save_state_to_json()

                # --- USER ACTIONS ---
        elif role == 'user':
            
            # 1. USER STORING ITEM
            if action == 'store_sendqr':
                obj['status'] = 'occupied'
                obj['customer'] = request.form.get('customer_name', 'No Email')
                obj['item'] = request.form.get('item_details', 'Unknown Item')
                obj['qrcode'] = secrets.token_hex(3).upper()
                obj['tracking_id'] = f"TRK-{secrets.token_hex(4).upper()}"
                obj['stored_time'] = datetime.now()
                obj['physical_state'] = 'waiting' # Return to rack instantly
                
                # --- NEW: SAVE THE CAPTURED CAMERA IMAGE ---
                captured_image_data = request.form.get('captured_image')
                if captured_image_data:
                    try:
                        import base64
                        # Remove the "data:image/jpeg;base64," part
                        image_data = captured_image_data.split(',')[1]
                        filename = f"capture_{obj['tracking_id']}.jpg"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        
                        with open(file_path, "wb") as fh:
                            fh.write(base64.b64decode(image_data))
                        
                        obj['image'] = filename # Save filename to the locker
                    except Exception as e:
                        print(f"Error saving image: {e}")
                # -------------------------------------------
                
                add_log("Lodged", f"Stored {obj['item']} for {obj['customer']}.")

                # Only send email if a real email exists
                if '@' in obj['customer']:
                    # Pass all 5 required arguments!
                    success = send_qr_email(obj['customer'], obj['item'], obj['qrcode'], obj['label'], obj['tracking_id'])
                    if success:
                        flash(f"Item Stored! Email sent to {obj['customer']}.", "success")
                    else:
                        flash("Item Stored! (Warning: Email failed to send)", "warning")
                else:
                    flash(f"Item Stored! PIN: {obj['qrcode']}", "success")
                    
                save_state_to_json()

            # 2. USER SCANNING PIN
            elif action == 'user_scan':
                if obj['qrcode'] and request.form.get('qrcode_input', '').upper() == obj['qrcode']:
                    obj['physical_state'] = 'calledout'
                    save_state_to_json()
                    flash("QR Code Verified! Bin is coming out.", "success")
                else:
                    flash("Invalid QR Code.", "danger")

            # 3. USER CLEARING UP (After taking item)
            elif action == 'user_clear_up':
                obj['status'] = 'empty'
                obj['customer'] = None
                obj['item'] = None
                obj['qrcode'] = None
                obj['image'] = None
                obj['tracking_id'] = None
                obj['physical_state'] = 'waiting' # Send bin back to rack
                
                add_log("Pickup", f"Customer retrieved item from {obj['label']}.")
                flash("Item taken! Bin data cleared and returned to rack.", "success")
                save_state_to_json()

    return redirect(request.referrer)

if __name__ == '__main__':
    if not os.path.exists(JSON_FILE): save_state_to_json()
    app.run(port=5001, debug=True)