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

            # --- NUEVO: CONFIGURACIÓN PARA AGUA SALADA (35.0 ‰) ---
            # Si tu salinidad es distinta (ej. 38.5), pon b'salt0385\r'
            self.serial_connection.write(b'salt0350\r')
            time.sleep(0.1)
            self.serial_connection.reset_input_buffer()

            self.serial_connection.write(b'mode0001\r')
            time.sleep(0.1)
            self.serial_connection.reset_input_buffer()
            
            return True
