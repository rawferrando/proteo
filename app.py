from flask import Flask, render_template, jsonify, request
import threading
import time
import os
import datetime
from sensor import PresensSensor
from collections import deque

app = Flask(__name__)

# --- CONFIGURACIÓN BLINDADA ---
sensor = PresensSensor()
measurements = deque(maxlen=50)
measuring = False
INTERVALO_GUARDADO = 300 
ultimo_guardado = 0

target_value = 19.7 
target_unit = 'oxygen' 

# --- VARIABLES DE ESTADO ---
modo_manual = False
estado_rele_actual = "APAGADO" # Esta variable chivará el estado a la web

# Al arrancar, nos aseguramos de que la válvula esté apagada (3.3V)
os.system("pinctrl set 17 op dh")

def measurement_loop():
    global measuring, target_value, target_unit, ultimo_guardado, modo_manual, estado_rele_actual
    
    while measuring:
        try:
            reading = sensor.read_measurement()
            if reading:
                o2_real = float(reading['oxygen']) 
                reading['oxygen'] = o2_real
                mg_l = o2_real * 0.091
                umol_l = mg_l * 31.251
                porcentaje_o2 = o2_real * 0.2095
                
                reading['porcentaje_o2'] = round(porcentaje_o2, 2)
                reading['mg_l'] = round(mg_l, 2)
                reading['umol_l'] = round(umol_l, 2)

                # --- LÓGICA DE RELÉ BLINDADA ---
                if modo_manual:
                    pass # En manual, el estado lo dictan los botones de la web
                else:
                    valor_actual = reading.get(target_unit, o2_real)
                    
                    if valor_actual > target_value:
                        if estado_rele_actual != "ENCENDIDO":
                            print(f"DEBUG: {target_unit} ({valor_actual}) > SET ({target_value}) -> ON (0V)")
                            os.system("pinctrl set 17 op dl") 
                            estado_rele_actual = "ENCENDIDO"
                    else:
                        if estado_rele_actual != "APAGADO":
                            print(f"DEBUG: {target_unit} ({valor_actual}) <= SET ({target_value}) -> OFF (3.3V)")
                            os.system("pinctrl set 17 op dh") 
                            estado_rele_actual = "APAGADO"

                with threading.Lock():
                    measurements.append(reading)

                ahora = time.time()
                if ahora - ultimo_guardado >= INTERVALO_GUARDADO:
                    ruta_data = "/home/proteo/code/proteo/data"
                    if not os.path.exists(ruta_data): os.makedirs(ruta_data)
                    archivo = os.path.join(ruta_data, "registro_aurora.txt")
                    existe = os.path.exists(archivo)
                    with open(archivo, "a") as f:
                        if not existe:
                            f.write("Fecha_Hora\t%O2 s.a.\tmg/L\tumol/L\tTemperatura\n")
                        fecha_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        temp = reading.get('temperature', 0)
                        f.write(f"{fecha_str}\t{o2_real:.2f}\t{mg_l:.2f}\t{umol_l:.2f}\t{temp}\n")
                    ultimo_guardado = ahora
                    print(f"--- [OK] Guardado en TXT: {fecha_str} ---")
        except Exception as e:
            print(f"Error en bucle: {e}")
        time.sleep(5)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        'measuring': measuring, 
        'target': target_value, 
        'target_unit': target_unit,
        'modo_manual': modo_manual,
        'estado_rele': estado_rele_actual, # Mandamos el estado físico real a la web
        'measurements': list(measurements)
    })

@app.route('/api/history')
def get_history():
    ruta = "/home/proteo/code/proteo/data/registro_aurora.txt"
    if not os.path.exists(ruta): return jsonify([])
    try:
        with open(ruta, 'r') as f:
            lines = f.readlines()
        if len(lines) <= 1: return jsonify([])
        data_lines = lines[1:]
        last_10 = data_lines[-10:]
        history = []
        for line in last_10:
            parts = line.strip().split('\t')
            if len(parts) >= 5:
                history.append({'date': parts[0], 'o2': parts[1], 'mgl': parts[2], 'umol': parts[3], 'temp': parts[4]})
        return jsonify(history)
    except:
        return jsonify([])

@app.route('/api/start', methods=['POST'])
def start():
    global measuring, ultimo_guardado
    if not measuring:
        if sensor.connect():
            measuring = True
            ultimo_guardado = 0 
            threading.Thread(target=measurement_loop, daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/api/stop', methods=['POST'])
def stop():
    global measuring, modo_manual, estado_rele_actual
    measuring = False
    modo_manual = False 
    os.system("pinctrl set 17 op dh")
    estado_rele_actual = "APAGADO" # Al detener, apagamos por seguridad y actualizamos estado
    return jsonify({'status': 'stopped'})

@app.route('/api/settings', methods=['POST'])
def settings():
    global target_value, target_unit
    data = request.get_json()
    target_value = float(data.get('target', 19.7))
    target_unit = data.get('unit', 'oxygen')
    return jsonify({'status': 'success'})

@app.route('/api/relay/manual', methods=['POST'])
def relay_manual():
    global modo_manual, estado_rele_actual
    data = request.get_json()
    accion = data.get('accion') 

    if accion == "AUTO":
        modo_manual = False
        return jsonify({'status': 'Modo Automático'})
    
    modo_manual = True
    if accion == "ON":
        os.system("pinctrl set 17 op dl") 
        estado_rele_actual = "ENCENDIDO"
    elif accion == "OFF":
        os.system("pinctrl set 17 op dh") 
        estado_rele_actual = "APAGADO"
        
    return jsonify({'status': f'Modo Manual: {estado_rele_actual}'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
