import serial
import time
import re
from typing import Optional, Dict
from datetime import datetime

class PresensSensor:
    def __init__(self, port='/dev/ttyUSB0', baudrate=19200, timeout=2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None
        self.last_reading = None
        
    def connect(self):
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            time.sleep(1)
            self.serial_connection.reset_input_buffer()
            
            # Desactivamos el guardado en flash para no quemar el chip
            self.serial_connection.write(b'mmwr0000\r')
            time.sleep(0.1)
            self.serial_connection.reset_input_buffer()

            self.serial_connection.write(b'mode0001\r')
            time.sleep(0.1)
            self.serial_connection.reset_input_buffer()
            
            return True
        except Exception as e:
            print(f"Error connecting to sensor: {e}")
            return False
    
    def disconnect(self):
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.write(b'mmwr0001\r')
                time.sleep(0.1)
            except:
                pass
            self.serial_connection.close()
    
    def parse_response(self, response: str, decimal_places: int = 2) -> Optional[Dict]:
        pattern = r'N\d+;A(\d+);P(\d+);T(\d+);O(\d+);E(\d+)'
        match = re.match(pattern, response)
        if match:
            amplitude, phase, temp, oxygen, error = match.groups()
            return {
                'timestamp': datetime.now().isoformat(),
                'amplitude': int(amplitude),
                'phase': int(phase) / 100,
                'temperature': int(temp) / 100,
                'oxygen': int(oxygen) / (10 ** decimal_places),
                'error': int(error)
            }
        return None
    
    def read_measurement(self) -> Optional[Dict]:
        """Interroga al sensor por TODAS las magnitudes, diagnósticos y raw data"""
        if not self.serial_connection or not self.serial_connection.is_open:
            if not self.connect():
                return None
        
        try:
            results = {
                'ref_amplitude': 0, 'pact_mbar': 0.0, 'salinity': 0.0, 'pulse_counter': 0,
                'oxygen_as': 0.0, 'oxygen_o2': 0.0, 'oxygen_mgl': 0.0, 'oxygen_umol': 0.0,
                'oxygen_ugl': 0.0, 'oxygen_hpa': 0.0, 'oxygen_torr': 0.0, 'oxygen_ppm_gas': 0.0,
                'amplitude': 0, 'phase': 0.0, 'temperature': 0.0, 'error': 0
            }

            # 1. SOLICITAMOS DIAGNÓSTICOS COMPLETOS (Raw Data + Salud del sistema)
            self.serial_connection.reset_input_buffer()
            self.serial_connection.write(b'repo\r')
            time.sleep(1.0) # Damos tiempo a que escupa todo el texto
            repo_lines = self.serial_connection.readlines()
            repo_text = "".join([line.decode('utf-8', errors='ignore') for line in repo_lines])

            # Extraemos Amplitud de Referencia, Presión, Salinidad y Pulsos
            ref_match = re.search(r'RefAmpl:\s*(\d+)', repo_text)
            if ref_match: results['ref_amplitude'] = int(ref_match.group(1))

            pact_match = re.search(r'PACT in mbar:\s*([\d\.]+)', repo_text)
            if pact_match: results['pact_mbar'] = float(pact_match.group(1))

            salt_match = re.search(r'Salinity:\s*([\d\.]+)', repo_text)
            if salt_match: results['salinity'] = float(salt_match.group(1))

            pulse_match = re.search(r'Pulse counts:\s*(\d+)', repo_text)
            if pulse_match: results['pulse_counter'] = int(pulse_match.group(1))

            # 2. SOLICITAMOS TODAS LAS UNIDADES DE OXÍGENO
            units = {
                '0000': ('oxygen_as', 2), '0001': ('oxygen_o2', 2),
                '0002': ('oxygen_hpa', 2), '0003': ('oxygen_torr', 2),
                '0004': ('oxygen_mgl', 4), '0005': ('oxygen_umol', 2),
                '0006': ('oxygen_ppm_gas', 4), '0007': ('oxygen_ugl', 2)
            }

            base_data = False
            for ucode, (uname, dec) in units.items():
                self.serial_connection.write(f'oxyu{ucode}\r'.encode())
                time.sleep(0.05)
                self.serial_connection.reset_input_buffer()
                self.serial_connection.write(b'data\r')
                time.sleep(0.25) # El manual pide ~300ms entre lecturas
                resp = self.serial_connection.readline().decode('utf-8', errors='ignore').strip()
                parsed = self.parse_response(resp, decimal_places=dec)
                
                if parsed:
                    results[uname] = parsed['oxygen']
                    if not base_data: # Solo necesitamos coger esto una vez
                        results['amplitude'] = parsed['amplitude']
                        results['phase'] = parsed['phase']
                        results['temperature'] = parsed['temperature']
                        results['error'] = parsed['error']
                        base_data = True

            # Volvemos a % a.s. por defecto
            self.serial_connection.write(b'oxyu0000\r')
            time.sleep(0.1)

            # Compatibilidad para app.py
            results['oxygen'] = results['oxygen_as']
            results['porcentaje_o2'] = results['oxygen_o2']
            results['mg_l'] = results['oxygen_mgl']
            results['umol_l'] = results['oxygen_umol']

            self.last_reading = results
            return results
                
        except Exception as e:
            print(f"Error reading from sensor: {e}")
            return None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
