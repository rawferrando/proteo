from flask import Flask, render_template, jsonify, request
from gpiozero import OutputDevice
import threading
import time
import os
import datetime
from sensor import PresensSensor
from collections import deque

app = Flask(__name__)

# --- CONFIGURACIÓN ---
sensor = PresensSensor()
rele = OutputDevice(23, active_high=False) 

measurements = deque(maxlen=50)
measuring = False
target_oxygen = 19.7 

# --- VARIABLES PARA EXCEL ---
INTERVALO_GUARDADO = 300 # 5 minutos
ultimo_guardado = 0

def measurement_loop():
    global measuring, target_oxygen, ultimo_guardado
    while measuring:
        try:
            reading = sensor.read_measurement()
            if reading:
                # O2 viene multiplicado por 10 del sensor
                o2_real = reading['oxygen'] / 10.0
                reading['oxygen'] = o2_real
                
                # --- CÁLCULOS DE UNIDADES ---
                mg_l = o2_real * 0.091
                umol_l = mg_l * 31.251
                reading['mg_l'] = round(mg_l, 2)
                reading['umol_l'] = round(umol_l, 2)
                
                # Lógica del Relé (Nitrógeno)
                if o2_real > target_oxygen:
                    rele.on()
                else:
                    rele.off()
                
                with threading.Lock():
                    measurements.append(reading)
                
                # --- GUARDADO CADA 5 MINUTOS EN EXCEL ---
                tiempo_actual = time.time()
                if tiempo_actual - ultimo_guardado >= INTERVALO_GUARDADO:
                    ahora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    archivo_excel = "data/registro_aurora.txt"
                    
                    if not os.path.exists('data'): os.makedirs('data')
                    if not os.path.exists(archivo_excel):
                        with open(archivo_excel, "w") as f:
                            f.write("Fecha_Hora\t%O2\tmg/L\tumol/L\tTemperatura\n")
                    
                    temp = reading.get('temperature', 0)
                    
                    with open(archivo_excel, "a") as f:
                        f.write(f"{ahora_str}\t{o2_real:.2f}\t{mg_l:.2f}\t{umol_l:.2f}\t{temp}\n")
                    
                    ultimo_guardado = tiempo_actual
                    print(f"Datos guardados en Excel a las {ahora_str}")

        except Exception as e:
            print(f"Error: {e}")
        time.sleep(5)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        'measuring': measuring,
        'target': target_oxygen,
        'measurements': list(measurements)
    })

@app.route('/api/start', methods=['POST'])
def start():
    global measuring, ultimo_guardado
    if not measuring:
        if not os.path.exists('data'): os.makedirs('data')
        if sensor.connect():
            measuring = True
            ultimo_guardado = 0  # Fuerzo guardado al iniciar
            threading.Thread(target=measurement_loop, daemon=True).start()
    return jsonify({'status': 'started' if measuring else 'error'})

@app.route('/api/stop', methods=['POST'])
def stop():
    global measuring
    measuring = False
    rele.off()
    return jsonify({'status': 'stopped'})

@app.route('/api/settings', methods=['POST'])
def settings():
    global target_oxygen
    data = request.get_json()
    target_oxygen = float(data.get('target', 19.7))
    return jsonify({'status': 'success', 'target': target_oxygen})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
