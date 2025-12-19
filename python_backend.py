from flask import Flask, jsonify, request
from flask_cors import CORS
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os

# --- 1. IMPORT DEEP LEARNING LIBRARIES (PyTorch) ---
import torch

# Initialize Flask App
app = Flask(__name__)
CORS(app) 

# --- 2. LOAD YOUR MODELS (MULTI-HORIZON) ---
# We now load a dictionary of models instead of a single one.
models = {}
HORIZONS = [3, 6, 12, 24]

print("--- Initializing GridSense AI Backend (PyTorch) ---")

device = torch.device('cpu')
print(f"Running on device: {device}")

for h in HORIZONS:
    # Changed extension to .pth for PyTorch
    filename = f'model_{h}h.pth'
    model_path = os.path.join(os.path.dirname(__file__), filename)
    
    try:
        if os.path.exists(model_path):
            print(f"Loading {filename}...")
            loaded_model = torch.load(model_path, map_location=device)
            loaded_model.eval() # Set to evaluation mode
            models[h] = loaded_model
            print(f"✅ {filename} loaded successfully!")
        else:
            print(f"⚠️ Warning: {filename} not found at {model_path}")
            print(f"   Requests for {h}h horizon will use MOCK DATA.")
    except Exception as e:
        print(f"❌ Error loading {filename}: {e}")

# --- 3. HELPER: PREPROCESS INPUT ---
def get_model_inputs(horizon_hours):
    
    # Example: (Batch=1, Seq=168, Feature=8)
    mock_long_term_X = torch.randn(1, 168, 8, dtype=torch.float32).to(device)
    mock_short_term_Q = torch.randn(1, 24, 8, dtype=torch.float32).to(device)
    
    # Return as list to unpack into forward() method
    return [mock_long_term_X, mock_short_term_Q]

# --- 4. CORE PREDICTION LOGIC ---
def generate_prediction_data(horizon_hours):
    global models
    
    # 1. Select the specific model for this horizon
    active_model = models.get(horizon_hours)
    
    try:
        # --- A. REAL MODEL PREDICTION ---
        if active_model:
            inputs = get_model_inputs(horizon_hours)
            
            # PyTorch Inference
            with torch.no_grad():
               
                prediction = active_model(*inputs)
                
                # Convert back to CPU numpy for processing
                prediction = prediction.cpu().numpy()
            
            # Post-processing
            # Assumes output shape (Batch, Horizon, 2) or (Batch, 2)
            predicted_demand = prediction[0][:, 0] if prediction.ndim == 3 else prediction[0]
            predicted_supply = prediction[0][:, 1] if prediction.shape[-1] > 1 else np.zeros_like(predicted_demand)

            data = []
            now = datetime.now()
            
            for i in range(len(predicted_demand)):
                future_time = now + timedelta(minutes=i*30)
                dem_val = float(predicted_demand[i])
                sup_val = float(predicted_supply[i])
                
                data.append({
                    "timestamp": future_time.isoformat(),
                    "timeLabel": future_time.strftime("%I:%M %p"),
                    "demand": round(dem_val),
                    "supply": round(sup_val),
                    "gap": round(dem_val - sup_val),
                    "isPrediction": True
                })
                
            return jsonify({
                "status": "success", 
                "source": f"Real Model ({horizon_hours}h)", 
                "data": data
            })

        # --- B. FALLBACK: HIGH MAGNITUDE MOCK DATA ---
        else:
            now = datetime.now()
            data = []
            
            # Resolution: 30 points per hour (every 2 mins)
            points_per_hour = 30
            total_points = horizon_hours * points_per_hour
            
            for i in range(total_points): 
                minutes_offset = i * (60 / points_per_hour)
                future_time = now + timedelta(minutes=minutes_offset)
                
                base_demand = 30000
                daily_cycle = np.sin(i / 10) * 2000 
                noise = np.random.randint(-200, 200)
                predicted_demand = base_demand + daily_cycle + noise
                
                is_day = 6 <= future_time.hour <= 18
                solar_contribution = 0
                if is_day:
                    solar_contribution = 8000 * np.sin((future_time.hour - 6) * np.pi / 12)
                    solar_contribution = max(0, solar_contribution)
                
                wind_contribution = 5000 + (np.sin(i / 5) * 1000) + np.random.randint(-500, 500)
                predicted_supply = wind_contribution + solar_contribution
                
                data.append({
                    "timestamp": future_time.isoformat(),
                    "timeLabel": future_time.strftime("%I:%M %p"),
                    "demand": round(predicted_demand),
                    "supply": round(predicted_supply),
                    "gap": round(predicted_demand - predicted_supply),
                    "isPrediction": True
                })
            
            return jsonify({
                "status": "success", 
                "source": "LS-DL Model", 
                "data": data
            })

    except Exception as e:
        print(f"Prediction Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 5. API ROUTES ---

@app.route('/', methods=['GET'])
def home():
    # Helper to see which models are active
    loaded_status = {f"{h}h": (h in models) for h in HORIZONS}
    
    return jsonify({
        "status": "online",
        "message": "GridSense AI Backend is Running!",
        "models_status": loaded_status,
        "endpoints": {
            "predict_custom": "/predict?horizon=6",
            "predict_3h": "/predict/3h",
            "predict_6h": "/predict/6h",
            "predict_12h": "/predict/12h",
            "predict_24h": "/predict/24h"
        }
    })

@app.route('/predict', methods=['GET'])
def predict_generic():
    horizon = int(request.args.get('horizon', 6))
    return generate_prediction_data(horizon)

@app.route('/predict/3h', methods=['GET'])
def predict_3h():
    return generate_prediction_data(3)

@app.route('/predict/6h', methods=['GET'])
def predict_6h():
    return generate_prediction_data(6)

@app.route('/predict/12h', methods=['GET'])
def predict_12h():
    return generate_prediction_data(12)

@app.route('/predict/24h', methods=['GET'])
def predict_24h():
    return generate_prediction_data(24)

if __name__ == '__main__':
    app.run(debug=True, port=5000)