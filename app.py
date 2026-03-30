from flask import Flask, render_template, jsonify, request, send_file
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
INTERVALO_GUARDADO = 5 # 5 segundos
ultimo_guardado = 0

target_value = 19.7 
target_unit = 'oxygen' 

# --- VARIABLES DE ESTADO ---
modo_manual = False
estado_rele_actual = "APAGADO" 

os.system("pinctrl set 17 op dh")

def measurement_loop():
    global measuring, target_value, target_unit, ultimo_guardado, modo_manual, estado_rele_actual
    
    while measuring:
        try:
            r = sensor.read_measurement()
            if r:
                # --- LÓGICA DE RELÉ BLINDADA ---
                if modo_manual:
                    pass 
                else:
                    valor_actual = r.get(target_unit, r.get('oxygen_as', 0))
                    
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
                    measurements.append(r)

                # --- GUARDADO DEL SUPER-CSV ---
                ahora = time.time()
                if ahora - ultimo_guardado >= INTERVALO_GUARDADO:
                    ruta_data = "/home/proteo/code/proteo/data"
                    if not os.path.exists(ruta_data): os.makedirs(ruta_data)
                    archivo = os.path.join(ruta_data, "registro_aurora.csv")
                    
                    cabecera = "Fecha_Hora,%a.s.,%O2,mg/L,umol/L,ug/L,hPa,Torr,ppm_gas,Temperatura_C,Fase,Amplitud_Senal,Amplitud_Ref,Error,Pulsos,PACT_mbar,Salinidad\n"
                    
                    # Sistema Automático Anti-Errores de Columnas
                    existe = os.path.exists(archivo)
                    if existe:
                        with open(archivo, "r") as f:
                            primera_linea = f.readline()
                        if primera_linea != cabecera:
                            os.rename(archivo, archivo.replace(".csv", f"_antiguo_{int(time.time())}.csv"))
                            existe = False

                    with open(archivo, "a") as f:
                        if not existe:
                            f.write(cabecera)
                        
                        fecha_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        linea_datos = (
                            f"{fecha_str},"
                            f"{r.get('oxygen_as',0):.2f},"
                            f"{r.get('oxygen_o2',0):.2f},"
                            f"{r.get('oxygen_mgl',0):.4f},"
                            f"{r.get('oxygen_umol',0):.2f},"
                            f"{r.get('oxygen_ugl',0):.2f},"
                            f"{r.get('oxygen_hpa',0):.2f},"
                            f"{r.get('oxygen_torr',0):.2f},"
                            f"{r.get('oxygen_ppm_gas',0):.4f},"
                            f"{r.get('temperature',0):.2f},"
                            f"{r.get('phase',0):.2f},"
                            f"{r.get('amplitude',0)},"
                            f"{r.get('ref_amplitude',0)},"
                            f"{r.get('error',0)},"
                            f"{r.get('pulse_counter',0)},"
                            f"{r.get('pact_mbar',0):.2f},"
                            f"{r.get('salinity',0):.2f}\n"
                        )
                        f.write(linea_datos)
                    
                    ultimo_guardado = ahora
                    print(f"--- [OK] Super-CSV guardado: {fecha_str} ---")
        except Exception as e:
            print(f"Error en bucle: {e}")
        time.sleep(1) 

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
        'estado_rele': estado_rele_actual, 
        'measurements': list(measurements)
    })

@app.route('/api/history')
def get_history():
    ruta = "/home/proteo/code/proteo/data/registro_aurora.csv"
    if not os.path.exists(ruta): return jsonify([])
    try:
        with open(ruta, 'r') as f:
            lines = f.readlines()
        if len(lines) <= 1: return jsonify([])
        data_lines = lines[1:]
        last_10 = data_lines[-10:]
        history = []
        for line in last_10:
            parts = line.strip().split(',') 
            if len(parts) >= 10: 
                history.append({'date': parts[0], 'o2': parts[1], 'mgl': parts[3], 'umol': parts[4], 'temp': parts[9]})
        return jsonify(history)
    except:
        return jsonify([])

# --- NUEVA RUTA PARA DESCARGAR EL CSV ---
@app.route('/api/download')
def download_csv():
    ruta = "/home/proteo/code/proteo/data/registro_aurora.csv"
    if os.path.exists(ruta):
        return send_file(ruta, as_attachment=True, download_name="registro_aurora.csv")
    return "Archivo no encontrado", 404

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
    estado_rele_actual = "APAGADO" 
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
