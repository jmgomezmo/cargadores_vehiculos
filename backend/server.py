import asyncio
import logging
import websockets
import os
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv
from ocpp.routing import on
from ocpp.v16 import ChargePoint as cp
from ocpp.v16.enums import Action, RegistrationStatus, AuthorizationStatus
from ocpp.v16 import call_result, call
from aiohttp import web

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

connected_chargers = {}

class DatabaseHandler:
    @staticmethod
    def get_connection():
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"), host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT")
        )
        with conn.cursor() as cur:
            cur.execute("SET search_path TO ocpp;")
        return conn

class CynergiaxChargePoint(cp):
    def __init__(self, id, connection):
        super().__init__(id, connection)
        self.active_transaction_id = None

    @on(Action.boot_notification)
    async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        try:
            with DatabaseHandler.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO cargadores (ocpp_id, estado_actual, marca, modelo)
                        VALUES (%s, 'Available', %s, %s)
                        ON CONFLICT (ocpp_id) DO UPDATE SET estado_actual = 'Available';
                    """, (self.id, charge_point_vendor, charge_point_model))
                    conn.commit()
            logging.info(f"✅ Cargador {self.id} conectado a DB (Español).")
        except Exception as e:
            logging.error(f"Error ETL Boot: {e}")
        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=30, status=RegistrationStatus.accepted
        )

    @on(Action.status_notification)
    async def on_status_notification(self, connector_id, error_code, status, **kwargs):
        try:
            with DatabaseHandler.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE cargadores SET estado_actual = %s, ultima_conexion = CURRENT_TIMESTAMP WHERE ocpp_id = %s;", (status, self.id))
                    conn.commit()
        except Exception:
            pass
        return call_result.StatusNotification()

    @on(Action.heartbeat)
    async def on_heartbeat(self, **kwargs):
        return call_result.Heartbeat(current_time=datetime.now(timezone.utc).isoformat())

    @on(Action.start_transaction)
    async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
        trans_id = 0
        try:
            with DatabaseHandler.get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Validar Usuario y Cargador
                    cur.execute("""
                        SELECT u.id_usuario, c.id_cargador 
                        FROM usuarios u CROSS JOIN cargadores c
                        WHERE u.id_tag = %s AND c.ocpp_id = %s
                    """, (id_tag, self.id))
                    auth_result = cur.fetchone()
                    
                    if not auth_result:
                        return call_result.StartTransaction(transaction_id=0, id_tag_info={'status': AuthorizationStatus.invalid})
                    
                    id_user, id_cp = auth_result
                    
                    # 2. Registrar Inicio de Sesión
                    cur.execute("""
                        INSERT INTO sesiones_carga (id_cargador, id_usuario, medidor_inicio, fecha_inicio)
                        VALUES (%s, %s, %s, %s) RETURNING id_sesion;
                    """, (id_cp, id_user, meter_start, timestamp))
                    trans_id = cur.fetchone()[0]
                    
                    # 3. Transición de Estado de Reserva (Pendiente -> Activa)
                    cur.execute("""
                        UPDATE reservas SET estado = 'Activa' 
                        WHERE id_usuario = %s AND id_cargador = %s AND estado = 'Pendiente';
                    """, (id_user, id_cp))
                    
                    conn.commit()
                    
            self.active_transaction_id = trans_id
            logging.info(f"▶️ Sesión {trans_id} iniciada para {self.id} y Reserva Activada.")
            return call_result.StartTransaction(transaction_id=trans_id, id_tag_info={'status': AuthorizationStatus.accepted})
        except Exception as e:
            logging.error(f"Error StartTx: {e}")
            return call_result.StartTransaction(transaction_id=0, id_tag_info={'status': AuthorizationStatus.invalid})

        
    @on(Action.meter_values)
    async def on_meter_values(self, connector_id, meter_value, **kwargs):
        try:
            trans_id = kwargs.get('transaction_id', self.active_transaction_id)
            
            # Evitar procesar telemetría sin ID de sesión
            if not trans_id:
                logging.warning(f"Telemetría ignorada del cargador {self.id} (Sin ID de sesión)")
                return call_result.MeterValues()
                
            with DatabaseHandler.get_connection() as conn:
                with conn.cursor() as cur:
                    for point in meter_value:
                        for sample in point['sampled_value']:
                            cur.execute("""
                                INSERT INTO telemetria (id_sesion, measurand, valor, unidad, recorded_at)
                                VALUES (%s, %s, %s, %s, %s);
                            """, (trans_id, sample.get('measurand'), sample.get('value'), sample.get('unit'), point['timestamp']))
                    conn.commit()
        except Exception as e:
            logging.error(f"Error MeterValues: {e}")
            
        return call_result.MeterValues()

    @on(Action.stop_transaction)
    async def on_stop_transaction(self, meter_stop, timestamp, transaction_id, **kwargs):
        try:
            self.active_transaction_id = None
            with DatabaseHandler.get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Traer datos para cálculo financiero
                    cur.execute("""
                        SELECT t.medidor_inicio, tar.precio_por_kwh
                        FROM sesiones_carga t CROSS JOIN (SELECT * FROM tarifas WHERE valido_hasta IS NULL LIMIT 1) tar
                        WHERE t.id_sesion = %s;
                    """, (transaction_id,))
                    row = cur.fetchone()
                    
                    if row:
                        meter_start, precio_kwh = row
                        energia_kwh = (float(meter_stop) - float(meter_start)) / 1000.0
                        costo_total = energia_kwh * float(precio_kwh)
                        
                        # 2. Cerrar Sesión de Carga
                        cur.execute("""
                            UPDATE sesiones_carga 
                            SET medidor_fin = %s, fecha_fin = %s, energia_kwh = %s, costo_energia = %s, motivo_detencion = %s
                            WHERE id_sesion = %s;
                        """, (meter_stop, timestamp, energia_kwh, costo_total, kwargs.get('reason'), transaction_id))
                        
                        # 3. Transición de Estado de Reserva (Activa -> Finalizada)
                        cur.execute("""
                            UPDATE reservas SET estado = 'Finalizada'
                            WHERE id_cargador = (SELECT id_cargador FROM sesiones_carga WHERE id_sesion = %s) 
                            AND estado = 'Activa';
                        """, (transaction_id,))
                        
                        conn.commit()
            logging.info(f"⏹️ Sesión {transaction_id} detenida financieramente y Reserva Finalizada.")
        except Exception as e:
            logging.error(f"Error StopTx: {e}")
        return call_result.StopTransaction(id_tag_info={'status': AuthorizationStatus.accepted})

# --- MICRO-SERVIDOR INTERNO ---
async def remote_start_handler(request):
    data = await request.json()
    cp_id = data.get("charge_point_id")
    id_tag = data.get("id_tag")

    if cp_id in connected_chargers:
        cp_instance = connected_chargers[cp_id]
        req = call.RemoteStartTransaction(id_tag=id_tag)
        try:
            response = await cp_instance.call(req)
            if response.status == 'Accepted':
                return web.json_response({"status": "success"})
            return web.json_response({"status": "rejected"}, status=400)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"error": "Cargador offline"}, status=404)

async def remote_stop_handler(request):
    data = await request.json()
    cp_id = data.get("charge_point_id")

    if cp_id in connected_chargers:
        cp_instance = connected_chargers[cp_id]
        tx_id = cp_instance.active_transaction_id
        
        # Rescate de memoria: Si el hardware se reconectó y la RAM está vacía, recuperar de la BD
        if not tx_id:
            try:
                with DatabaseHandler.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id_sesion FROM sesiones_carga 
                            WHERE id_cargador = (SELECT id_cargador FROM cargadores WHERE ocpp_id = %s) 
                            AND fecha_fin IS NULL ORDER BY fecha_inicio DESC LIMIT 1;
                        """, (cp_id,))
                        row = cur.fetchone()
                        if row:
                            tx_id = row[0]
                            cp_instance.active_transaction_id = tx_id
            except Exception:
                pass
        
        if not tx_id:
            return web.json_response({"error": "No hay sesión activa"}, status=400)
            
        req = call.RemoteStopTransaction(transaction_id=tx_id)
        try:
            response = await cp_instance.call(req)
            if response.status == 'Accepted':
                return web.json_response({"status": "success"})
            return web.json_response({"status": "rejected"}, status=400)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
            
    return web.json_response({"error": "Cargador offline"}, status=404)

async def on_connect(websocket):
    try:
        charge_point_id = websocket.request.path.strip('/')
    except AttributeError:
        charge_point_id = websocket.path.strip('/')
        
    cp_instance = CynergiaxChargePoint(charge_point_id, websocket)
    connected_chargers[charge_point_id] = cp_instance
    try:
        await cp_instance.start()
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if charge_point_id in connected_chargers:
            del connected_chargers[charge_point_id]

async def main():
    ocpp_server = await websockets.serve(on_connect, '0.0.0.0', 8080, subprotocols=['ocpp1.6'])
    logging.info("🚀 Orquestador B2B2C escuchando en puerto 8080...")

    app = web.Application()
    app.router.add_post('/remote_start', remote_start_handler)
    app.router.add_post('/remote_stop', remote_stop_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 9090)
    await site.start()

    await ocpp_server.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())